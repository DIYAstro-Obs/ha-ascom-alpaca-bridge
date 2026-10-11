"""DataUpdateCoordinator for Alpaca Bridge."""
import asyncio
import contextlib
import math
from datetime import timedelta
from typing import Any, Callable, Dict

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .identity import device_uid as _device_uid
from .const import (
    DOMAIN, DEFAULT_SCAN_INTERVAL, MIN_SCAN_INTERVAL, MAX_CONCURRENT_REQUESTS, API_BASE, LOGGER,
    DEFAULT_MAX_SENSOR_AGE,
)


OBSERVINGCONDITIONS_PROPS = (
    "cloudcover", "dewpoint", "humidity", "pressure", "temperature", "windspeed", "starfwhm",
    "skybrightness", "skytemperature", "winddirection", "skyquality", "rainrate", "windgust",
)

DOME_CAPABILITIES = (
    "canfindhome", "canpark", "cansetaltitude", "cansetazimuth", "cansetpark", "cansetshutter", "canslave", "cansyncazimuth",
)

TELESCOPE_CAPABILITIES = (
    "canpark", "canfindhome", "canslewasync", "canslewaltazasync", "cansettracking", "canpulseguide",
    "cansetguiderates", "cansetdeclinationrate", "cansetrightascensionrate", "cansync", "cansyncaltaz", "cansetpierside",
)

CAMERA_CAPABILITIES = (
    "canabortexposure", "canasymmetricbin", "canfastreadout", "cangetcoolerpower", "cansetccdtemperature",
    "canstopexposure", "canpulseguide",
)


class AlpacaConnectionError(Exception):
    """A request got no usable answer (no connection, timeout, server error), as opposed to an Alpaca error."""


class AlpacaDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Alpaca data from the server."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        devices: list,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        max_sensor_age: int = DEFAULT_MAX_SENSOR_AGE,
        uid_host: "str | None" = None,
    ) -> None:
        """Initialize."""
        self.host = host
        self.port = port
        self.devices = devices
        self.uid_host = uid_host or host
        self.base_url = f"http://{host}:{port}/{API_BASE}"
        self._client_transaction_id = 1
        self.max_sensor_age = max_sensor_age

        # Requests of a device that run at the same time during a poll (created per poll, in the running loop)
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        # The poll that follows a command (a new command replaces it)
        self._smart_poll_task = None
        # Properties already reported as HTTP 400 / 404 (one warning, not one per poll)
        self._warned: set = set()

        # Values the user entered in number / select entities and did not send to the device yet. They are kept
        # here and not in `data`, because every poll builds `data` from scratch. A button reads them and clears
        # them once it has applied them.
        self.targets: Dict[str, Dict[str, Any]] = {}

        # Properties that do not change while the device runs (capabilities, names, driver info), fetched once.
        self._static_cache: Dict[Any, Any] = {}

        # Answers / transport failures of the poll in progress: a poll without any answer means "not reachable".
        self._responses = 0
        self._failures = 0

        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=max(MIN_SCAN_INTERVAL, scan_interval)),
        )

    def set_scan_interval(self, seconds: float) -> None:
        """Poll every `seconds` (not faster than MIN_SCAN_INTERVAL)."""
        self.update_interval = timedelta(seconds=max(MIN_SCAN_INTERVAL, seconds))

    def device_uid(self, device: dict) -> str:
        """The unique ID of a device: its Alpaca UniqueID, or one built from the server and the device."""
        return _device_uid(device, self.devices, self.uid_host)

    def get_client_transaction_id(self) -> int:
        """Get and increment the ClientTransactionID, resetting before reaching the 32-bit unsigned limit."""
        self._client_transaction_id += 1
        if self._client_transaction_id > 2000000000:
            self._client_transaction_id = 1
        return self._client_transaction_id

    # --- target values (entered by the user, not sent yet) ---------------------------------------
    def get_target(self, dev_key: str, key: str, default: Any = None) -> Any:
        return self.targets.get(dev_key, {}).get(key, default)

    def set_target(self, dev_key: str, key: str, value: Any) -> None:
        self.targets.setdefault(dev_key, {})[key] = value

    def clear_target(self, dev_key: str, key: str) -> None:
        self.targets.get(dev_key, {}).pop(key, None)

    def target_group(self, dev_key: str, group: str) -> Dict[str, Any]:
        """Settings that are applied together by one button ("telescope", "camera"): property -> value."""
        return self.targets.setdefault(dev_key, {}).setdefault(group, {})

    # --- polling ---------------------------------------------------------------------------------
    async def _async_update_data(self) -> Dict[str, Dict[str, Any]]:
        """Update data via HTTP."""
        self._responses = 0
        self._failures = 0
        session = async_get_clientsession(self.hass)
        # A server that does not answer would cost the 10 s timeout of every one of the ~100 requests (found
        # live: a stopped ASCOM Remote server made a setup take over a minute): one quick request first.
        if not await self._server_reachable(session):
            raise UpdateFailed(f"Alpaca server {self.host}:{self.port} is not reachable")
        self._semaphores = {
            f"{device['DeviceType'].lower()}_{device['DeviceNumber']}": asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
            for device in self.devices
        }
        data: Dict[str, Dict[str, Any]] = {}
        tasks = []

        for device in self.devices:
            dev_type = device["DeviceType"].lower()
            dev_num = device["DeviceNumber"]
            dev_key = f"{dev_type}_{dev_num}"
            data[dev_key] = {}

            tasks.append(self._fetch_common_meta(session, data, dev_key, dev_type, dev_num))

            if dev_type == "observingconditions":
                for p in OBSERVINGCONDITIONS_PROPS:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
                    # age of the measurement: timesincelastupdate?SensorName=<prop>
                    tasks.append(self._fetch_age_task(session, data, dev_key, dev_type, dev_num, p))
            elif dev_type == "safetymonitor":
                tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "issafe"))
            elif dev_type == "switch":
                tasks.append(self._fetch_switch_task(session, data, dev_key, dev_num))
            elif dev_type == "dome":
                tasks.append(self._fetch_dome_capabilities(session, data, dev_key, dev_num))
                for p in ["shutterstatus", "altitude", "azimuth", "athome", "atpark", "slaved", "slewing"]:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
            elif dev_type == "covercalibrator":
                tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "coverstate"))
                tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "calibratorstate"))
                tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "brightness"))
                tasks.append(self._fetch_covercal_meta(session, data, dev_key, dev_num))
            elif dev_type == "telescope":
                tasks.append(self._fetch_telescope_capabilities(session, data, dev_key, dev_num))
                for p in [
                    # position & coordinates
                    "rightascension", "declination", "altitude", "azimuth", "siderealtime",
                    "sitelatitude", "sitelongitude", "siteelevation", "focallength",
                    "aperturediameter", "aperturearea", "equatorialsystem", "alignmentmode",
                    # status & tracking
                    "tracking", "trackingrate", "atpark", "athome", "slewing",
                    "sideofpier", "doesrefraction", "ispulseguiding", "slewsettletime", "utcdate",
                    # rates
                    "declinationrate", "rightascensionrate", "guideratedeclination", "guideraterightascension",
                ]:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
            elif dev_type == "rotator":
                tasks.append(self._fetch_rotator_capabilities(session, data, dev_key, dev_num))
                for p in ["position", "targetposition", "stepsize", "ismoving", "reverse", "mechanicalposition"]:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
            elif dev_type == "filterwheel":
                tasks.append(self._fetch_filterwheel_meta(session, data, dev_key, dev_num))
                tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, "position"))
            elif dev_type == "focuser":
                tasks.append(self._fetch_focuser_capabilities(session, data, dev_key, dev_num))
                for p in ["position", "temperature", "ismoving", "tempcomp", "stepsize"]:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))
            elif dev_type == "camera":
                tasks.append(self._fetch_camera_capabilities(session, data, dev_key, dev_num))
                for p in [
                    "camerastate", "ccdtemperature", "coolerpower", "percentcompleted",
                    "electronsperadu", "fullwellcapacity", "maxadu", "pixelsizex", "pixelsizey",
                    "imageready", "lastexposurestarttime", "ispulseguiding", "cooleron", "fastreadout", "sensorname", "sensortype",
                    "gain", "offset", "binx", "biny", "readoutmode", "numx", "numy", "startx", "starty",
                    "heatsinktemperature", "setccdtemperature",
                    "maxbinx", "maxbiny", "gainmax", "gainmin", "offsetmax", "offsetmin", "exposuremax", "exposuremin",
                ]:
                    tasks.append(self._fetch_prop_task(session, data, dev_key, dev_type, dev_num, p))

        # Every request has its own 10 s timeout and a device that hangs only delays its own values (the limit
        # of requests at the same time is per device); this is the limit of the whole poll.
        try:
            async with asyncio.timeout(60):
                if tasks:
                    await asyncio.gather(*tasks)
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API: {str(err) or type(err).__name__}") from err

        # Every request failed at transport level and nothing answered: the server is not there. (Missing
        # properties are normal, a missing server is not: this makes the entities unavailable and, at startup,
        # the setup is retried by Home Assistant.)
        if self._failures and not self._responses:
            raise UpdateFailed(f"Alpaca server {self.host}:{self.port} is not reachable")

        return data

    async def _server_reachable(self, session) -> bool:
        """True when the server answers at all (any HTTP answer counts)."""
        url = f"http://{self.host}:{self.port}/management/apiversions"
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)):
                return True
        except Exception as err:
            LOGGER.debug("Alpaca server %s:%s does not answer: %s", self.host, self.port, err)
            return False

    async def _fetch_prop_task(self, session, data, dev_key, dev_type, dev_num, prop):
        """Helper to fetch a single property and assign it to the data dict."""
        val = await self.fetch_property(session, dev_type, dev_num, prop)
        if val is not None:
            data[dev_key][prop] = val

    async def _fetch_age_task(self, session, data, dev_key, dev_type, dev_num, prop_name):
        """Fetch timesincelastupdate for a given sensor property and store as age_<prop>."""
        val = await self.fetch_property(session, dev_type, dev_num, f"timesincelastupdate?SensorName={prop_name}")
        if val is not None:
            data[dev_key][f"age_{prop_name}"] = float(val)

    # --- properties that do not change (fetched once) -------------------------------------------------
    async def _fetch_static(self, session, dev_type, dev_num, props) -> "tuple[dict, bool]":
        """Fetch properties in parallel. Returns ({prop: value or None}, complete).

        `complete` is False when a request failed at transport level; the caller must not cache such a result,
        otherwise a server that was briefly unreachable leaves wrong capabilities behind. An Alpaca error
        ("not implemented") is a definitive answer: the value is None and the result is complete.
        """
        results = await asyncio.gather(
            *(self.fetch_property(session, dev_type, dev_num, p, strict=True) for p in props),
            return_exceptions=True,
        )
        values, complete = {}, True
        for prop, result in zip(props, results):
            if isinstance(result, AlpacaConnectionError):
                values[prop], complete = None, False
            elif isinstance(result, BaseException):
                raise result
            else:
                values[prop] = result
        return values, complete

    async def _static(self, key, session, dev_type, dev_num, props, build: Callable[[dict], Any]) -> Any:
        """The `build`-result of the given properties, fetched once and cached when the fetch was complete."""
        if key in self._static_cache:
            return self._static_cache[key]
        values, complete = await self._fetch_static(session, dev_type, dev_num, props)
        result = build(values)
        if complete:
            self._static_cache[key] = result
        return result

    async def _fetch_common_meta(self, session, data, dev_key, dev_type, dev_num):
        """Driver version and info."""
        meta = await self._static(
            ("meta", dev_key), session, dev_type, dev_num, ("driverversion", "driverinfo"),
            lambda v: {"driverversion": v["driverversion"] or "Unknown", "driverinfo": v["driverinfo"] or "Unknown"},
        )
        data[dev_key].update(meta)

    async def _fetch_covercal_meta(self, session, data, dev_key, dev_num):
        """CoverCalibrator maxbrightness (written into the data dict so switch.py and number.py can use it)."""

        def build(v):
            if v["maxbrightness"] is None:
                LOGGER.warning("Could not fetch maxbrightness for CoverCalibrator %s, defaulting to 255", dev_key)
                return 255
            return int(v["maxbrightness"])

        data[dev_key]["maxbrightness"] = await self._static(
            ("maxbrightness", dev_key), session, "covercalibrator", dev_num, ("maxbrightness",), build
        )

    async def _fetch_dome_capabilities(self, session, data, dev_key, dev_num):
        data[dev_key]["capabilities"] = await self._static(
            ("caps", dev_key), session, "dome", dev_num, DOME_CAPABILITIES,
            lambda v: {p: bool(x) for p, x in v.items()},
        )

    async def _fetch_telescope_capabilities(self, session, data, dev_key, dev_num):
        data[dev_key]["capabilities"] = await self._static(
            ("caps", dev_key), session, "telescope", dev_num, TELESCOPE_CAPABILITIES,
            lambda v: {p: bool(x) for p, x in v.items()},
        )

    async def _fetch_rotator_capabilities(self, session, data, dev_key, dev_num):
        data[dev_key]["capabilities"] = await self._static(
            ("caps", dev_key), session, "rotator", dev_num, ("canreverse",),
            lambda v: {"canreverse": bool(v["canreverse"])},
        )

    async def _fetch_focuser_capabilities(self, session, data, dev_key, dev_num):
        def build(v):
            return {
                "absolute": bool(v["absolute"]),
                "tempcompavailable": bool(v["tempcompavailable"]),
                "maxstep": int(v["maxstep"]) if v["maxstep"] is not None else None,
                "maxincrement": int(v["maxincrement"]) if v["maxincrement"] is not None else None,
            }

        caps = await self._static(
            ("caps", dev_key), session, "focuser", dev_num,
            ("absolute", "tempcompavailable", "maxstep", "maxincrement"), build,
        )
        data[dev_key]["capabilities"] = caps
        for key in ("maxstep", "maxincrement"):
            if caps.get(key) is not None:
                data[dev_key][key] = caps[key]

    async def _fetch_camera_capabilities(self, session, data, dev_key, dev_num):
        def build(v):
            caps = {p: bool(v[p]) for p in CAMERA_CAPABILITIES}
            modes = v["readoutmodes"]
            caps["readoutmodes"] = modes if isinstance(modes, list) else []
            # sensor size in pixels: the limit of the subframe settings (None when the camera does not say)
            caps["cameraxsize"] = v["cameraxsize"]
            caps["cameraysize"] = v["cameraysize"]
            return caps

        data[dev_key]["capabilities"] = await self._static(
            ("caps", dev_key), session, "camera", dev_num,
            CAMERA_CAPABILITIES + ("readoutmodes", "cameraxsize", "cameraysize"), build,
        )

    async def _fetch_filterwheel_meta(self, session, data, dev_key, dev_num):
        """Filter names and focus offsets."""
        meta = await self._static(
            ("filterwheel", dev_key), session, "filterwheel", dev_num, ("names", "focusoffsets"),
            lambda v: {
                "names": v["names"] if v["names"] is not None else [],
                "focusoffsets": v["focusoffsets"] if v["focusoffsets"] is not None else [],
            },
        )
        data[dev_key].update(meta)

    async def _fetch_switch_task(self, session, data, dev_key, dev_num):
        """Helper to fetch switch states."""
        maxswitch = await self.fetch_property(session, "switch", dev_num, "maxswitch")
        if maxswitch is None:
            return
        data[dev_key]["maxswitch"] = maxswitch

        for i in range(maxswitch):
            val = await self.fetch_property(session, "switch", dev_num, f"getswitch?Id={i}")
            if val is not None:
                data[dev_key][f"switch_{i}"] = val

            val2 = await self.fetch_property(session, "switch", dev_num, f"getswitchvalue?Id={i}")
            if val2 is not None:
                data[dev_key][f"switchvalue_{i}"] = val2

            props = tuple(
                f"{name}?Id={i}" for name in ("canwrite", "getswitchname", "minswitchvalue", "maxswitchvalue", "switchstep")
            )

            def build(v, props=props, i=i):
                canwrite, name, min_val, max_val, step_val = (v[p] for p in props)
                min_val = min_val if min_val is not None else 0.0
                max_val = max_val if max_val is not None else 1.0
                step_val = step_val if step_val is not None else 1.0
                return {
                    "canwrite": canwrite if canwrite is not None else True,
                    "name": name if name is not None else f"Switch {i}",
                    "min": min_val,
                    "max": max_val,
                    "step": step_val,
                    "is_analog": (max_val - min_val > 1.0) or (step_val != 1.0 and step_val > 0.0),
                }

            meta = await self._static(("switch", dev_key, i), session, "switch", dev_num, props, build)
            data[dev_key][f"canwrite_{i}"] = meta["canwrite"]
            data[dev_key][f"name_{i}"] = meta["name"]
            data[dev_key][f"min_{i}"] = meta["min"]
            data[dev_key][f"max_{i}"] = meta["max"]
            data[dev_key][f"step_{i}"] = meta["step"]
            data[dev_key][f"is_analog_{i}"] = meta["is_analog"]

    # --- requests ----------------------------------------------------------------------------------
    async def fetch_property(self, session, dev_type, dev_num, prop, *, strict: bool = False) -> Any:
        """Fetch a specific property from the Alpaca API.

        Returns the value, or None when there is none (not implemented, error answer, no connection). With
        `strict` a transport failure (no connection, timeout, HTTP 5xx) raises AlpacaConnectionError instead,
        so the caller can tell "this server does not have it" from "the server did not answer".
        """
        tid = self.get_client_transaction_id()

        # Determine if we need to append ?ClientTransactionID= or &ClientTransactionID=
        sep = "&" if "?" in prop else "?"
        url = f"{self.base_url}/{dev_type.lower()}/{dev_num}/{prop}{sep}ClientID=1&ClientTransactionID={tid}"

        warned_key = (dev_type.lower(), dev_num, prop.split("?")[0])
        try:
            # at most MAX_CONCURRENT_REQUESTS of a device at the same time
            semaphore = self._semaphores.get(f"{dev_type.lower()}_{dev_num}")
            async with semaphore or contextlib.nullcontext():
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    self._responses += 1
                    if response.status == 200:
                        self._warned.discard(warned_key)
                        res = await response.json()
                        # ErrorNumber 0 means success.
                        # Some devices return ErrorNumber 1024 (Not Implemented) for optional properties.
                        if res.get("ErrorNumber") == 0:
                            value = res.get("Value")
                            # NaN / infinity (a camera that does not know its temperature, ...) is no value:
                            # Home Assistant refuses such a state for a numeric sensor
                            if isinstance(value, float) and not math.isfinite(value):
                                return None
                            return value
                    elif response.status in (400, 404):
                        # one warning per property until it answers again, not one per poll
                        level = LOGGER.debug if warned_key in self._warned else LOGGER.warning
                        self._warned.add(warned_key)
                        level(
                            "HTTP %s for %s – check that the device exists on the server (URL: %s)",
                            response.status, prop, url,
                        )
                    else:
                        LOGGER.debug("HTTP %s for %s (URL: %s)", response.status, prop, url)
                        if strict and response.status >= 500:
                            raise AlpacaConnectionError(f"HTTP {response.status} for {prop}")
                    return None
        except AlpacaConnectionError:
            raise
        except Exception as err:
            self._failures += 1
            LOGGER.debug("Request failed for %s: %s", url, err)
            if strict:
                raise AlpacaConnectionError(f"Request for {prop} failed: {err}") from err
            return None

    async def send_command(self, dev_type: str, dev_num: int, command: str, data: dict = None) -> bool:
        """Send a PUT command to the Alpaca API.

        Returns True when the device accepted the command. Anything else raises HomeAssistantError with the
        message of the device, so the UI and automations see that the command did not work.
        """
        session = async_get_clientsession(self.hass)
        tid = self.get_client_transaction_id()
        url = f"{self.base_url}/{dev_type.lower()}/{dev_num}/{command}"

        payload = {
            "ClientID": "1",
            "ClientTransactionID": str(tid)
        }
        if data:
            payload.update(data)

        try:
            async with session.put(url, data=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    raise HomeAssistantError(f"{dev_type} {dev_num}: {command} failed, the server answered HTTP {response.status}")
                res = await response.json()
        except HomeAssistantError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"{dev_type} {dev_num}: {command} failed, no answer from {self.host}:{self.port} ({err})") from err

        err_num = res.get("ErrorNumber")
        if err_num != 0:
            message = res.get("ErrorMessage") or "no message"
            LOGGER.debug("Alpaca command %s failed (error %s): %s", command, err_num, message)
            raise HomeAssistantError(f"{dev_type} {dev_num}: {command} failed: {message} (Alpaca error {err_num})")

        # Schedule a fast follow-up poll to catch quick state changes (Smart Polling)
        self._schedule_smart_poll()
        return True

    async def prepare_slew(self, dev_type: str, dev_num: int, *, altaz: bool) -> None:
        """Get the mount into the state a slew needs.

        A parked mount cannot slew. An Alt/Az slew needs tracking off, an equatorial slew needs it on (as
        N.I.N.A. does it as well).
        """
        dev_key = f"{dev_type.lower()}_{dev_num}"
        data = (self.data or {}).get(dev_key, {})
        if data.get("atpark"):
            raise ServiceValidationError(f"{dev_type} {dev_num} is parked, unpark it first")
        tracking = data.get("tracking")
        if altaz and tracking:
            await self.send_command(dev_type, dev_num, "tracking", {"Tracking": "False"})
            await asyncio.sleep(1)  # let the mount process the change
        elif not altaz and tracking is False and data.get("capabilities", {}).get("cansettracking"):
            await self.send_command(dev_type, dev_num, "tracking", {"Tracking": "True"})

    def _schedule_smart_poll(self) -> None:
        """Start the follow-up poll of a command; a poll that is still running is replaced."""
        self.cancel_smart_poll()
        self._smart_poll_task = self.hass.async_create_task(self._smart_poll())

    def cancel_smart_poll(self) -> None:
        """Stop the follow-up poll (new command, unload)."""
        task, self._smart_poll_task = self._smart_poll_task, None
        if task is not None and not task.done():
            task.cancel()

    async def _smart_poll(self) -> None:
        """Intelligently poll a few times after a command to catch state changes quickly.
        This provides a 'snappy' UI response without hammering the API constantly.
        """
        for _ in range(3):
            await asyncio.sleep(1.5)
            await self.async_refresh()

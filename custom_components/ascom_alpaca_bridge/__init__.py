"""The Alpaca Bridge integration."""
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, PLATFORMS, CONF_HOST, CONF_PORT, CONF_DEVICES, CONF_UID_HOST, DEFAULT_SCAN_INTERVAL, LOGGER,
    CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE,
    SERVICE_SLEW_TO_COORDINATES, SERVICE_SLEW_TO_ALT_AZ, SERVICE_ROTATOR_MOVE, SERVICE_ROTATOR_SYNC,
    SERVICE_FOCUSER_MOVE, SERVICE_DOME_SLEW_AZ, SERVICE_DOME_SLEW_ALT, SERVICE_DOME_SYNC_AZ,
    SERVICE_CAMERA_START_EXPOSURE, SERVICE_CAMERA_PULSEGUIDE, SERVICE_CAMERA_SET_ROI,
    SERVICE_TELESCOPE_PULSEGUIDE,
)
from .coordinator import AlpacaDataUpdateCoordinator
from .identity import device_uid, fallback_uid

CONF_SCAN_INTERVAL = "scan_interval"

# Every service takes an optional `device_id`: with one device of the type it is not needed, with several it
# says which one is meant.
DEVICE_ID = {vol.Optional("device_id"): cv.string}

PULSEGUIDE_FIELDS = {
    vol.Required("direction"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3)),
    vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30000)),
}

# camera_set_roi: ASCOM has the subframe as four properties: (property, parameter name, service field)
ROI_PROPERTIES = (
    ("numx", "NumX", "num_x"),
    ("numy", "NumY", "num_y"),
    ("startx", "StartX", "start_x"),
    ("starty", "StartY", "start_y"),
)

SERVICE_NAMES = (
    SERVICE_SLEW_TO_COORDINATES, SERVICE_SLEW_TO_ALT_AZ, SERVICE_ROTATOR_MOVE, SERVICE_ROTATOR_SYNC,
    SERVICE_FOCUSER_MOVE, SERVICE_DOME_SLEW_AZ, SERVICE_DOME_SLEW_ALT, SERVICE_DOME_SYNC_AZ,
    SERVICE_CAMERA_START_EXPOSURE, SERVICE_CAMERA_PULSEGUIDE, SERVICE_CAMERA_SET_ROI,
    SERVICE_TELESCOPE_PULSEGUIDE,
)


# --- finding the device a service call is meant for --------------------------------------------------
def _devices_of_type(hass: HomeAssistant, dev_type: str):
    for coordinator in hass.data.get(DOMAIN, {}).values():
        for device in coordinator.devices:
            if device["DeviceType"].lower() == dev_type:
                yield coordinator, device


def _resolve_device(hass: HomeAssistant, call: ServiceCall, dev_type: str):
    """The (coordinator, device) a service call is for. Several candidates without device_id are an error:
    a slew or an exposure must not go to every mount or camera."""
    candidates = list(_devices_of_type(hass, dev_type))
    device_id = call.data.get("device_id")
    if device_id:
        registered = dr.async_get(hass).async_get(device_id)
        if registered is None:
            raise ServiceValidationError(f"Unknown device {device_id}")
        uids = {identifier[1] for identifier in registered.identifiers if identifier[0] == DOMAIN}
        candidates = [(c, d) for c, d in candidates if c.device_uid(d) in uids]
        if not candidates:
            raise ServiceValidationError(f"The selected device is not a {dev_type} of this integration")
    if not candidates:
        raise ServiceValidationError(f"No {dev_type} is configured")
    if len(candidates) > 1:
        raise ServiceValidationError(f"There are several {dev_type} devices: select one with device_id")
    return candidates[0]


def _register(hass, name, dev_type, fields, command, params, capability=None):
    """Register a service that sends one command to the device.

    `params` turns the call data into the Alpaca parameters; `capability` is the can... property the device
    has to report.
    """

    async def _handle(call: ServiceCall) -> None:
        coordinator, device = _resolve_device(hass, call, dev_type)
        number = device["DeviceNumber"]
        caps = (coordinator.data or {}).get(f"{dev_type}_{number}", {}).get("capabilities", {})
        if capability and not caps.get(capability):
            raise ServiceValidationError(f"The {dev_type} does not support {name} ({capability} is false)")
        if name in (SERVICE_SLEW_TO_COORDINATES, SERVICE_SLEW_TO_ALT_AZ):
            await coordinator.prepare_slew(dev_type, number, altaz=name == SERVICE_SLEW_TO_ALT_AZ)
        LOGGER.debug("Service %s: %s", name, call.data)
        await coordinator.send_command(dev_type, number, command, params(call.data))
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, name, _handle, schema=vol.Schema({**DEVICE_ID, **fields}))


def _register_services(hass: HomeAssistant) -> None:
    _register(
        hass, SERVICE_SLEW_TO_COORDINATES, "telescope",
        {
            vol.Required("ra"): vol.All(vol.Coerce(float), vol.Range(min=0, max=24)),
            vol.Required("dec"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        },
        "slewtocoordinatesasync",
        lambda d: {"RightAscension": str(d["ra"]), "Declination": str(d["dec"])},
        capability="canslewasync",
    )
    _register(
        hass, SERVICE_SLEW_TO_ALT_AZ, "telescope",
        {
            vol.Required("alt"): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
            vol.Required("az"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
        },
        "slewtoaltazasync",
        lambda d: {"Altitude": str(d["alt"]), "Azimuth": str(d["az"])},
        capability="canslewaltazasync",
    )
    _register(
        hass, SERVICE_TELESCOPE_PULSEGUIDE, "telescope", PULSEGUIDE_FIELDS, "pulseguide",
        lambda d: {"Direction": str(d["direction"]), "Duration": str(d["duration"])},
        capability="canpulseguide",
    )
    _register(
        hass, SERVICE_ROTATOR_MOVE, "rotator", {vol.Required("position"): vol.Coerce(float)}, "move",
        lambda d: {"Position": str(d["position"])},
    )
    _register(
        hass, SERVICE_ROTATOR_SYNC, "rotator",
        {vol.Required("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360))}, "sync",
        lambda d: {"Position": str(d["position"])},
    )
    _register(
        hass, SERVICE_FOCUSER_MOVE, "focuser", {vol.Required("position"): vol.Coerce(int)}, "move",
        lambda d: {"Position": str(int(d["position"]))},
    )
    _register(
        hass, SERVICE_DOME_SLEW_AZ, "dome",
        {vol.Required("azimuth"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360))}, "slewtoazimuth",
        lambda d: {"Azimuth": str(d["azimuth"])},
        capability="cansetazimuth",
    )
    _register(
        hass, SERVICE_DOME_SLEW_ALT, "dome",
        {vol.Required("altitude"): vol.All(vol.Coerce(float), vol.Range(min=0, max=90))}, "slewtoaltitude",
        lambda d: {"Altitude": str(d["altitude"])},
        capability="cansetaltitude",
    )
    _register(
        hass, SERVICE_DOME_SYNC_AZ, "dome",
        {vol.Required("azimuth"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360))}, "synctoazimuth",
        lambda d: {"Azimuth": str(d["azimuth"])},
        capability="cansyncazimuth",
    )
    _register(
        hass, SERVICE_CAMERA_START_EXPOSURE, "camera",
        {
            vol.Required("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
            vol.Optional("light", default=True): vol.Coerce(bool),
        },
        "startexposure",
        lambda d: {"Duration": str(d["duration"]), "Light": str(d["light"])},
    )
    _register(
        hass, SERVICE_CAMERA_PULSEGUIDE, "camera", PULSEGUIDE_FIELDS, "pulseguide",
        lambda d: {"Direction": str(d["direction"]), "Duration": str(d["duration"])},
        capability="canpulseguide",
    )

    async def _handle_camera_set_roi(call: ServiceCall) -> None:
        """The four subframe values are sent one after the other (ASCOM has no single call for them)."""
        coordinator, device = _resolve_device(hass, call, "camera")
        for prop, param, field in ROI_PROPERTIES:
            await coordinator.send_command("camera", device["DeviceNumber"], prop, {param: str(call.data[field])})
        await coordinator.async_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_CAMERA_SET_ROI, _handle_camera_set_roi,
        schema=vol.Schema({
            **DEVICE_ID,
            vol.Required("start_x"): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required("start_y"): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required("num_x"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required("num_y"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        }),
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Version 1 -> 2: devices with an Alpaca UniqueID move from the host based ID to it (see identity.py).

    The entity IDs, names and history stay, only the internal unique IDs and the device identifiers change.
    A device without a usable UniqueID keeps its host based ID. Everything comes from the data of the entry.
    """
    if entry.version == 1:
        await _migrate_unique_ids(hass, entry)
        hass.config_entries.async_update_entry(entry, version=2)
    return True


async def _migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    host = entry.data.get(CONF_UID_HOST) or entry.data[CONF_HOST]
    devices = entry.data.get(CONF_DEVICES, [])
    moves = {}  # old unique ID of a device -> new one
    for device in devices:
        old, new = fallback_uid(device, host), device_uid(device, devices, host)
        if new != old:
            moves[old] = new
    if not moves:
        return

    longest_first = sorted(moves, key=len, reverse=True)

    @callback
    def _new_entity_unique_id(entity_entry):
        unique_id = entity_entry.unique_id
        for old in longest_first:
            if unique_id.startswith(old + "_"):
                return {"new_unique_id": moves[old] + unique_id[len(old):]}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _new_entity_unique_id)

    registry = dr.async_get(hass)
    for old, new in moves.items():
        registered = registry.async_get_device(identifiers={(DOMAIN, old)})
        if registered is not None and entry.entry_id in registered.config_entries:
            registry.async_update_device(registered.id, new_identifiers={(DOMAIN, new)})
    LOGGER.info("Migrated the unique IDs of %s device(s) of %s to their Alpaca UniqueID", len(moves), entry.title)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpaca Bridge from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    devices = entry.data.get(CONF_DEVICES, [])
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    max_sensor_age = entry.options.get(CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE)

    coordinator = AlpacaDataUpdateCoordinator(
        hass, host, port, devices, scan_interval, max_sensor_age, uid_host=entry.data.get(CONF_UID_HOST)
    )

    # raises ConfigEntryNotReady when the server does not answer: Home Assistant retries the setup
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates (e.g. polling interval change)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services (only once; they find the devices of all entries when they are called)
    if not hass.services.has_service(DOMAIN, SERVICE_SLEW_TO_COORDINATES):
        _register_services(hass)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    new_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    LOGGER.debug("Updating scan interval to %s seconds", new_interval)
    coordinator.set_scan_interval(new_interval)
    coordinator.max_sensor_age = entry.options.get(CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id).cancel_smart_poll()

    # Remove the services when the last entry is gone
    if not hass.data[DOMAIN]:
        for service in SERVICE_NAMES:
            hass.services.async_remove(DOMAIN, service)

    return unload_ok

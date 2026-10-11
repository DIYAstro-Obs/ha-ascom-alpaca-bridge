"""The Alpaca Bridge integration."""
import asyncio
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PLATFORMS, CONF_HOST, CONF_PORT, CONF_DEVICES, DEFAULT_SCAN_INTERVAL, LOGGER, CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE
from .coordinator import AlpacaDataUpdateCoordinator

CONF_SCAN_INTERVAL = "scan_interval"

SERVICE_SLEW_TO_COORDINATES = "slew_to_coordinates"
SERVICE_SLEW_TO_ALT_AZ = "slew_to_alt_az"

SLEW_COORDS_SCHEMA = vol.Schema({
    vol.Required("ra"): vol.All(vol.Coerce(float), vol.Range(min=0, max=24)),
    vol.Required("dec"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
})

SLEW_ALTAZ_SCHEMA = vol.Schema({
    vol.Required("alt"): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
    vol.Required("az"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
})

SERVICE_ROTATOR_MOVE = "rotator_move"
SERVICE_ROTATOR_SYNC = "rotator_sync"

ROTATOR_MOVE_SCHEMA = vol.Schema({
    vol.Required("position"): vol.Coerce(float),
})

ROTATOR_SYNC_SCHEMA = vol.Schema({
    vol.Required("position"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
})

SERVICE_FOCUSER_MOVE = "focuser_move"
FOCUSER_MOVE_SCHEMA = vol.Schema({
    vol.Required("position"): vol.Coerce(int),
})

SERVICE_DOME_SLEW_AZ = "dome_slew_az"
DOME_SLEW_AZ_SCHEMA = vol.Schema({
    vol.Required("azimuth"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
})

SERVICE_DOME_SLEW_ALT = "dome_slew_alt"
DOME_SLEW_ALT_SCHEMA = vol.Schema({
    vol.Required("altitude"): vol.All(vol.Coerce(float), vol.Range(min=0, max=90)),
})

SERVICE_DOME_SYNC_AZ = "dome_sync_az"
DOME_SYNC_AZ_SCHEMA = vol.Schema({
    vol.Required("azimuth"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
})

SERVICE_CAMERA_START_EXPOSURE = "camera_start_exposure"
CAMERA_START_EXPOSURE_SCHEMA = vol.Schema({
    vol.Required("duration"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    vol.Optional("light", default=True): vol.Coerce(bool),
})

SERVICE_TELESCOPE_PULSEGUIDE = "telescope_pulseguide"
SERVICE_CAMERA_PULSEGUIDE = "camera_pulseguide"
SERVICE_CAMERA_SET_ROI = "camera_set_roi"

CAMERA_SET_ROI_SCHEMA = vol.Schema({
    vol.Required("start_x"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Required("start_y"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Required("num_x"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    vol.Required("num_y"): vol.All(vol.Coerce(int), vol.Range(min=1)),
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alpaca Bridge from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    devices = entry.data.get(CONF_DEVICES, [])
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    max_sensor_age = entry.options.get(CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE)
    
    coordinator = AlpacaDataUpdateCoordinator(hass, host, port, devices, scan_interval, max_sensor_age)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listen for options updates (e.g. polling interval change)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register services (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_SLEW_TO_COORDINATES):
        async def _handle_slew_coords(call: ServiceCall) -> None:
            """Handle slew to RA/Dec service call."""
            ra = call.data["ra"]
            dec = call.data["dec"]
            # Find the first telescope coordinator that supports slew
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "telescope":
                        dev_key = f"telescope_{dev['DeviceNumber']}"
                        if coord.data.get(dev_key, {}).get("capabilities", {}).get("canslewasync"):
                            LOGGER.debug("Service slew_to_coordinates: RA=%s, Dec=%s", ra, dec)
                            await coord.send_command(
                                "telescope", dev["DeviceNumber"], "slewtocoordinatesasync",
                                {"RightAscension": str(ra), "Declination": str(dec)}
                            )
                            await coord.async_refresh()
                            return

        async def _handle_slew_altaz(call: ServiceCall) -> None:
            """Handle slew to Alt/Az service call."""
            alt = call.data["alt"]
            az = call.data["az"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "telescope":
                        dev_key = f"telescope_{dev['DeviceNumber']}"
                        if not coord.data.get(dev_key, {}).get("capabilities", {}).get("canslewaltazasync"):
                            continue
                            
                        # Disable tracking before Alt/Az slew (like N.I.N.A.)
                        if coord.data.get(dev_key, {}).get("tracking"):
                            LOGGER.debug("Service slew_to_alt_az: disabling tracking first")
                            await coord.send_command(
                                "telescope", dev["DeviceNumber"], "tracking",
                                {"Tracking": "False"}
                            )
                            await asyncio.sleep(1)
                        LOGGER.debug("Service slew_to_alt_az: Alt=%s, Az=%s", alt, az)
                        await coord.send_command(
                            "telescope", dev["DeviceNumber"], "slewtoaltazasync",
                            {"Altitude": str(alt), "Azimuth": str(az)}
                        )
                        await coord.async_refresh()
                        return

        hass.services.async_register(
            DOMAIN, SERVICE_SLEW_TO_COORDINATES, _handle_slew_coords, schema=SLEW_COORDS_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_SLEW_TO_ALT_AZ, _handle_slew_altaz, schema=SLEW_ALTAZ_SCHEMA
        )

        async def _handle_rotator_move(call: ServiceCall) -> None:
            """Handle relative move."""
            pos = call.data["position"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "rotator":
                        LOGGER.debug("Service rotator_move: Position=%s", pos)
                        await coord.send_command("rotator", dev["DeviceNumber"], "move", {"Position": str(pos)})
                        await coord.async_refresh()

        async def _handle_rotator_sync(call: ServiceCall) -> None:
            """Handle sync to position."""
            pos = call.data["position"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "rotator":
                        LOGGER.debug("Service rotator_sync: Position=%s", pos)
                        await coord.send_command("rotator", dev["DeviceNumber"], "sync", {"Position": str(pos)})
                        await coord.async_refresh()

        hass.services.async_register(
            DOMAIN, SERVICE_ROTATOR_MOVE, _handle_rotator_move, schema=ROTATOR_MOVE_SCHEMA
        )
        hass.services.async_register(
            DOMAIN, SERVICE_ROTATOR_SYNC, _handle_rotator_sync, schema=ROTATOR_SYNC_SCHEMA
        )

        async def _handle_focuser_move(call: ServiceCall) -> None:
            """Handle move for focuser."""
            pos = call.data["position"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "focuser":
                        LOGGER.debug("Service focuser_move: Position=%s", pos)
                        await coord.send_command("focuser", dev["DeviceNumber"], "move", {"Position": str(int(pos))})
                        await coord.async_refresh()

        hass.services.async_register(
            DOMAIN, SERVICE_FOCUSER_MOVE, _handle_focuser_move, schema=FOCUSER_MOVE_SCHEMA
        )

        async def _handle_dome_slew_az(call: ServiceCall) -> None:
            """Handle slew azimuth for dome."""
            val = call.data["azimuth"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "dome":
                        await coord.send_command("dome", dev["DeviceNumber"], "slewtoazimuth", {"Azimuth": str(val)})
                        await coord.async_refresh()
                        
        async def _handle_dome_slew_alt(call: ServiceCall) -> None:
            """Handle slew altitude for dome."""
            val = call.data["altitude"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "dome":
                        await coord.send_command("dome", dev["DeviceNumber"], "slewtoaltitude", {"Altitude": str(val)})
                        await coord.async_refresh()
                        
        async def _handle_dome_sync_az(call: ServiceCall) -> None:
            """Handle sync azimuth for dome."""
            val = call.data["azimuth"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "dome":
                        await coord.send_command("dome", dev["DeviceNumber"], "synctoazimuth", {"Azimuth": str(val)})
                        await coord.async_refresh()

        hass.services.async_register(DOMAIN, SERVICE_DOME_SLEW_AZ, _handle_dome_slew_az, schema=DOME_SLEW_AZ_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_DOME_SLEW_ALT, _handle_dome_slew_alt, schema=DOME_SLEW_ALT_SCHEMA)
        hass.services.async_register(DOMAIN, SERVICE_DOME_SYNC_AZ, _handle_dome_sync_az, schema=DOME_SYNC_AZ_SCHEMA)

        async def _handle_camera_start_exposure(call: ServiceCall) -> None:
            """Handle start exposure for camera."""
            duration = call.data["duration"]
            light = call.data.get("light", True)
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "camera":
                        LOGGER.debug("Service camera_start_exposure: Duration=%s, Light=%s", duration, light)
                        await coord.send_command("camera", dev["DeviceNumber"], "startexposure", {"Duration": str(duration), "Light": str(light)})
                        await coord.async_refresh()

        hass.services.async_register(DOMAIN, SERVICE_CAMERA_START_EXPOSURE, _handle_camera_start_exposure, schema=CAMERA_START_EXPOSURE_SCHEMA)

        async def _handle_telescope_pulseguide(call: ServiceCall) -> None:
            """Handle pulse guide for telescope."""
            direction = call.data["direction"]
            duration = call.data["duration"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "telescope":
                        LOGGER.debug("Service telescope_pulseguide: Dir=%s, Dur=%s", direction, duration)
                        await coord.send_command("telescope", dev["DeviceNumber"], "pulseguide", {"Direction": str(direction), "Duration": str(duration)})
                        
        async def _handle_camera_pulseguide(call: ServiceCall) -> None:
            """Handle pulse guide for camera."""
            direction = call.data["direction"]
            duration = call.data["duration"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "camera":
                        LOGGER.debug("Service camera_pulseguide: Dir=%s, Dur=%s", direction, duration)
                        await coord.send_command("camera", dev["DeviceNumber"], "pulseguide", {"Direction": str(direction), "Duration": str(duration)})

        async def _handle_camera_set_roi(call: ServiceCall) -> None:
            """Handle setting region of interest for camera."""
            start_x = call.data["start_x"]
            start_y = call.data["start_y"]
            num_x = call.data["num_x"]
            num_y = call.data["num_y"]
            for coord in hass.data[DOMAIN].values():
                for dev in coord.devices:
                    if dev["DeviceType"].lower() == "camera":
                        LOGGER.debug("Service camera_set_roi: StartX=%s, StartY=%s, NumX=%s, NumY=%s", start_x, start_y, num_x, num_y)
                        # We must send X, Y, Width, Height individually as the ASCOM standard defines them as individual properties
                        await coord.send_command("camera", dev["DeviceNumber"], "numx", {"NumX": str(num_x)})
                        await coord.send_command("camera", dev["DeviceNumber"], "numy", {"NumY": str(num_y)})
                        await coord.send_command("camera", dev["DeviceNumber"], "startx", {"StartX": str(start_x)})
                        await coord.send_command("camera", dev["DeviceNumber"], "starty", {"StartY": str(start_y)})
                        await coord.async_refresh()

        import voluptuous as vol
        import homeassistant.helpers.config_validation as cv
        PULSEGUIDE_SCHEMA = vol.Schema({
            vol.Required("direction"): vol.All(vol.Coerce(int), vol.Range(min=0, max=3)),
            vol.Required("duration"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30000)),
        })

        if SERVICE_TELESCOPE_PULSEGUIDE in globals():
            hass.services.async_register(DOMAIN, SERVICE_TELESCOPE_PULSEGUIDE, _handle_telescope_pulseguide, schema=PULSEGUIDE_SCHEMA)
        else:
            hass.services.async_register(DOMAIN, "telescope_pulseguide", _handle_telescope_pulseguide, schema=PULSEGUIDE_SCHEMA)
            
        if SERVICE_CAMERA_PULSEGUIDE in globals():
            hass.services.async_register(DOMAIN, SERVICE_CAMERA_PULSEGUIDE, _handle_camera_pulseguide, schema=PULSEGUIDE_SCHEMA)
        else:
            hass.services.async_register(DOMAIN, "camera_pulseguide", _handle_camera_pulseguide, schema=PULSEGUIDE_SCHEMA)

        if SERVICE_CAMERA_SET_ROI in globals():
            hass.services.async_register(DOMAIN, SERVICE_CAMERA_SET_ROI, _handle_camera_set_roi, schema=CAMERA_SET_ROI_SCHEMA)
        else:
            hass.services.async_register(DOMAIN, "camera_set_roi", _handle_camera_set_roi, schema=CAMERA_SET_ROI_SCHEMA)


    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    new_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    LOGGER.debug("Updating scan interval to %s seconds", new_interval)
    coordinator.update_interval = timedelta(seconds=new_interval)
    coordinator.max_sensor_age = entry.options.get(CONF_MAX_SENSOR_AGE, DEFAULT_MAX_SENSOR_AGE)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    # Remove services if no more entries
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SLEW_TO_COORDINATES)
        hass.services.async_remove(DOMAIN, SERVICE_SLEW_TO_ALT_AZ)
        hass.services.async_remove(DOMAIN, SERVICE_ROTATOR_MOVE)
        hass.services.async_remove(DOMAIN, SERVICE_ROTATOR_SYNC)
        hass.services.async_remove(DOMAIN, SERVICE_FOCUSER_MOVE)
        hass.services.async_remove(DOMAIN, SERVICE_DOME_SLEW_AZ)
        hass.services.async_remove(DOMAIN, SERVICE_DOME_SLEW_ALT)
        hass.services.async_remove(DOMAIN, SERVICE_DOME_SYNC_AZ)

    return unload_ok

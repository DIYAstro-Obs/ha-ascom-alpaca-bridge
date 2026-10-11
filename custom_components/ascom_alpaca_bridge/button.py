"""Button platform for Alpaca Bridge."""
import asyncio

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN, LOGGER
from .base import AlpacaEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the button platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})

            # Standard telescope action buttons
            if caps.get("canpark"):
                entities.append(AlpacaTelescopeButton(coordinator, device, "park", {"name": "Park", "icon": "mdi:parking"}))
                entities.append(AlpacaTelescopeButton(coordinator, device, "unpark", {"name": "Unpark", "icon": "mdi:car-brake-parking"}))
                
            if caps.get("canfindhome"):
                entities.append(AlpacaTelescopeButton(coordinator, device, "findhome", {"name": "Find Home", "icon": "mdi:home-search"}))
                
            # Abort slew should always be available if possible
            entities.append(AlpacaTelescopeButton(coordinator, device, "abortslew", {"name": "Abort Slew", "icon": "mdi:stop-circle"}))

            # Slew buttons
            if caps.get("canslewasync"):
                entities.append(AlpacaTelescopeSlewButton(
                    coordinator, device, "slewtocoordinatesasync",
                    {"name": "Slew to RA/Dec", "icon": "mdi:telescope"},
                    target_keys=("target_ra", "target_dec"),
                    param_names=("RightAscension", "Declination"),
                ))
                
            if caps.get("canslewaltazasync"):
                entities.append(AlpacaTelescopeSlewButton(
                    coordinator, device, "slewtoaltazasync",
                    {"name": "Slew to Alt/Az", "icon": "mdi:compass-rose"},
                    target_keys=("target_alt", "target_az"),
                    param_names=("Altitude", "Azimuth"),
                ))
                
            if caps.get("cansetpierside"):
                entities.append(AlpacaTelescopeFlipPierButton(coordinator, device))
                
            # Apply Telescope Settings Button
            entities.append(AlpacaTelescopeApplySettingsButton(coordinator, device))
                
        elif device["DeviceType"].lower() == "rotator":
            dev_key = f"rotator_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            entities.append(AlpacaRotatorHaltButton(coordinator, device))
            entities.append(AlpacaRotatorMoveButton(coordinator, device))
            if "position" in data:
                entities.append(AlpacaRotatorMoveAbsoluteAction(coordinator, device))
            entities.append(AlpacaRotatorSyncButton(coordinator, device))
        elif device["DeviceType"].lower() == "focuser":
            dev_key = f"focuser_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            entities.append(AlpacaFocuserHaltButton(coordinator, device))
            if caps.get("absolute") and "position" in data:
                entities.append(AlpacaFocuserMoveAction(coordinator, device))
        elif device["DeviceType"].lower() == "dome":
            dev_key = f"dome_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("cansetaltitude") and "altitude" in data:
                entities.append(AlpacaDomeSlewAction(coordinator, device, "altitude", "Slew Target Altitude", "mdi:telescope"))
            if caps.get("cansetazimuth") and "azimuth" in data:
                entities.append(AlpacaDomeSlewAction(coordinator, device, "azimuth", "Slew Target Azimuth", "mdi:telescope"))
            if caps.get("canfindhome"):
                entities.append(AlpacaDomeButton(coordinator, device, "findhome", "Find Home", "mdi:home-search"))
            if caps.get("canpark"):
                entities.append(AlpacaDomeButton(coordinator, device, "park", "Park", "mdi:parking"))
            if caps.get("cansetpark"):
                entities.append(AlpacaDomeButton(coordinator, device, "setpark", "Set Park", "mdi:map-marker"))
        elif device["DeviceType"].lower() == "camera":
            dev_key = f"camera_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            
            if caps.get("canabortexposure", False):
                entities.append(AlpacaCameraButton(coordinator, device, "abortexposure", "Abort Exposure", "mdi:camera-off"))
            if caps.get("canstopexposure", False):
                entities.append(AlpacaCameraButton(coordinator, device, "stopexposure", "Stop Exposure", "mdi:stop-circle-outline"))
                
            entities.append(AlpacaCameraStartExposureButton(coordinator, device))
            entities.append(AlpacaCameraApplySettingsButton(coordinator, device))
            
        elif device["DeviceType"].lower() == "covercalibrator":
            entities.append(AlpacaCalibratorBrightnessButton(coordinator, device))
            
        elif device["DeviceType"].lower() == "filterwheel":
            dev_key = f"filterwheel_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "names" in data and "position" in data:
                entities.append(AlpacaFilterWheelApplyButton(coordinator, device))


    if entities:
        async_add_entities(entities)


class AlpacaTelescopeButton(AlpacaEntity, ButtonEntity):
    """Simple telescope action button (Park, Unpark, etc.)."""

    def __init__(self, coordinator, device, command, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self._command = command
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{command}"
        self._attr_icon = config["icon"]

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Telescope %s: %s", self.dev_key, self._command)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, self._command
        )
        if success:
            await self.coordinator.async_refresh()


class AlpacaTelescopeSlewButton(AlpacaEntity, ButtonEntity):
    """Slew button that reads target coordinates from Number entities."""

    def __init__(self, coordinator, device, command, config, target_keys, param_names):
        """Initialize."""
        super().__init__(coordinator, device)
        self._command = command
        self._target_keys = target_keys  # e.g. ("target_ra", "target_dec")
        self._param_names = param_names  # e.g. ("RightAscension", "Declination")
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{command}"
        self._attr_icon = config["icon"]

    async def async_press(self) -> None:
        """Handle the button press – slew to target coordinates."""
        data = self.coordinator.data.get(self.dev_key, {})
        params = {}
        for key, param_name in zip(self._target_keys, self._param_names):
            value = self.coordinator.get_target(self.dev_key, key)
            if value is None:
                LOGGER.warning("Telescope %s: Cannot slew, %s not set", self.dev_key, key)
                return
            params[param_name] = str(value)

        # Alt/Az slew requires tracking to be off
        if self._command == "slewtoaltazasync" and data.get("tracking"):
            LOGGER.debug("Telescope %s: disabling tracking for Alt/Az slew", self.dev_key)
            await self.coordinator.send_command(
                self.dev_type, self.dev_num, "tracking",
                {"Tracking": "False"}
            )
            # Wait for telescope to process tracking change
            await asyncio.sleep(1)

        LOGGER.debug("Telescope %s: %s with %s", self.dev_key, self._command, params)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, self._command, params
        )
        if success:
            await self.coordinator.async_refresh()

class AlpacaRotatorHaltButton(AlpacaEntity, ButtonEntity):
    """Rotator Halt button."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Halt"
        self._attr_unique_id = f"{super().unique_id}_halt"
        self._attr_icon = "mdi:stop-circle"

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Rotator %s: Halt", self.dev_key)
        success = await self.coordinator.send_command(self.dev_type, self.dev_num, "halt")
        if success:
            await self.coordinator.async_refresh()

class AlpacaFocuserHaltButton(AlpacaEntity, ButtonEntity):
    """Focuser Halt button."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Halt"
        self._attr_unique_id = f"{super().unique_id}_halt"
        self._attr_icon = "mdi:stop-circle"

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Focuser %s: Halt", self.dev_key)
        success = await self.coordinator.send_command(self.dev_type, self.dev_num, "halt")
        if success:
            await self.coordinator.async_refresh()

class AlpacaDomeButton(AlpacaEntity, ButtonEntity):
    """Dome simple command button."""

    def __init__(self, coordinator, device, command, name, icon):
        """Initialize."""
        super().__init__(coordinator, device)
        self._command = command
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{command}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Dome %s: %s", self.dev_key, self._command)
        success = await self.coordinator.send_command(self.dev_type, self.dev_num, self._command)
        if success:
            await self.coordinator.async_refresh()

class AlpacaCameraButton(AlpacaEntity, ButtonEntity):
    """Camera simple command button."""

    def __init__(self, coordinator, device, command, name, icon):
        """Initialize."""
        super().__init__(coordinator, device)
        self._command = command
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{command}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle the button press."""
        LOGGER.debug("Camera %s: %s", self.dev_key, self._command)
        success = await self.coordinator.send_command(self.dev_type, self.dev_num, self._command)
        if success:
            await self.coordinator.async_refresh()

class AlpacaCameraStartExposureButton(AlpacaEntity, ButtonEntity):
    """Button to start an exposure using the target_exposure value."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Start Exposure"
        self._attr_unique_id = f"{super().unique_id}_startexposure"
        self._attr_icon = "mdi:camera-iris"

    async def async_press(self) -> None:
        """Handle the button press."""
        duration = self.coordinator.get_target(self.dev_key, "target_exposure", 1.0)
        LOGGER.debug("Camera %s: Start Exposure (Duration=%s)", self.dev_key, duration)
        success = await self.coordinator.send_command(self.dev_type, self.dev_num, "startexposure", {"Duration": str(duration), "Light": "True"})
        if success:
            await self.coordinator.async_refresh()


class AlpacaRotatorMoveButton(AlpacaEntity, ButtonEntity):
    """Button to perform a relative move on the rotator."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Move (Relative)"
        self._attr_unique_id = f"{super().unique_id}_move_relative_btn"
        self._attr_icon = "mdi:rotate-right"

    async def async_press(self) -> None:
        """Send relative move command using the stored move_relative value."""
        amount = self.coordinator.get_target(self.dev_key, "move_relative", 0.0)
        LOGGER.debug("Rotator %s: move (relative) %s°", self.dev_key, amount)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "move", {"Position": str(amount)}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})


class AlpacaRotatorSyncButton(AlpacaEntity, ButtonEntity):
    """Button to sync the rotator to a given position."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Sync"
        self._attr_unique_id = f"{super().unique_id}_sync_btn"
        self._attr_icon = "mdi:sync"

    async def async_press(self) -> None:
        """Send sync command using the stored sync_position value."""
        position = self.coordinator.get_target(self.dev_key, "sync_position", 0.0)
        LOGGER.debug("Rotator %s: sync to %s°", self.dev_key, position)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "sync", {"Position": str(position)}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})


class AlpacaFocuserMoveAction(AlpacaEntity, ButtonEntity):
    """Focuser Move button."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Move to Target"
        self._attr_unique_id = f"{super().unique_id}_move_target"
        self._attr_icon = "mdi:arrow-right-bold-circle-outline"

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        pos = self.coordinator.get_target(self.dev_key, "focuser_target_position", data.get("position"))
        if pos is not None:
            LOGGER.debug("Focuser %s: Move to %s", self.dev_key, int(pos))
            await self.coordinator.send_command(self.dev_type, self.dev_num, "move", {"Position": str(int(pos))})
            self.coordinator.clear_target(self.dev_key, "focuser_target_position")
            await self.coordinator.async_refresh()

class AlpacaRotatorMoveAbsoluteAction(AlpacaEntity, ButtonEntity):
    """Rotator Move Absolute button."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Move to Target Angle"
        self._attr_unique_id = f"{super().unique_id}_move_abs_btn"
        self._attr_icon = "mdi:rotate-right-variant"

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        pos = self.coordinator.get_target(self.dev_key, "rotator_target_position", data.get("position"))
        if pos is not None:
            LOGGER.debug("Rotator %s: move (absolute) to %s°", self.dev_key, pos)
            await self.coordinator.send_command(self.dev_type, self.dev_num, "moveabsolute", {"Position": str(pos)})
            self.coordinator.clear_target(self.dev_key, "rotator_target_position")
            await self.coordinator.async_refresh()

class AlpacaDomeSlewAction(AlpacaEntity, ButtonEntity):
    """Dome Slew button."""
    def __init__(self, coordinator, device, prop, name, icon):
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_slew_{prop}"
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        val = self.coordinator.get_target(self.dev_key, f"dome_target_{self.prop}", data.get(self.prop))
        if val is not None:
            cmd = "slewtoaltitude" if self.prop == "altitude" else "slewtoazimuth"
            param_name = "Altitude" if self.prop == "altitude" else "Azimuth"
            LOGGER.debug("Dome %s: %s to %s", self.dev_key, cmd, val)
            await self.coordinator.send_command(self.dev_type, self.dev_num, cmd, {param_name: str(val)})
            self.coordinator.clear_target(self.dev_key, f"dome_target_{self.prop}")
            await self.coordinator.async_refresh()

class AlpacaTelescopeFlipPierButton(AlpacaEntity, ButtonEntity):
    """Button to flip the pier side."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Flip Pier"
        self._attr_unique_id = f"{super().unique_id}_flippier"
        self._attr_icon = "mdi:scale-balance"

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        current = data.get("sideofpier")
        if current is None or current == -1:
            LOGGER.error("Cannot flip pier: current pier side unknown")
            return
        target = 1 if current == 0 else 0
        LOGGER.debug("Telescope %s: flipping pier from %s to %s", self.dev_key, current, target)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "sideofpier", {"SideOfPier": str(target)}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "sideofpier" in self.coordinator.data.get(self.dev_key, {})

class AlpacaCalibratorBrightnessButton(AlpacaEntity, ButtonEntity):
    """Button to apply target brightness to the CoverCalibrator."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Set Brightness"
        self._attr_unique_id = f"{super().unique_id}_set_brightness"
        self._attr_icon = "mdi:brightness-6"

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        target = self.coordinator.get_target(self.dev_key, "target_brightness", data.get("brightness", 0))
        LOGGER.debug("CoverCalibrator %s: setting brightness to %s", self.dev_key, int(target))
        await self.coordinator.send_command(
            self.dev_type, self.dev_num, "calibratoron",
            {"Brightness": str(int(target))}
        )
        self.coordinator.clear_target(self.dev_key, "target_brightness")
        await self.coordinator.async_refresh()

class AlpacaFilterWheelApplyButton(AlpacaEntity, ButtonEntity):
    """Button to apply the selected target filter."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Move to Target Filter"
        self._attr_unique_id = f"{super().unique_id}_apply_filter"
        self._attr_icon = "mdi:camera-iris"

    async def async_press(self) -> None:
        """Handle the button press."""
        data = self.coordinator.data.get(self.dev_key, {})
        pos = self.coordinator.get_target(self.dev_key, "target_position", data.get("position"))
        if pos is not None and pos >= 0:
            LOGGER.debug("FilterWheel %s: setting position to %s", self.dev_key, pos)
            await self.coordinator.send_command(
                self.dev_type, self.dev_num, "position",
                {"Position": str(pos)}
            )
            self.coordinator.clear_target(self.dev_key, "target_position")
            await self.coordinator.async_refresh()

class AlpacaCameraApplySettingsButton(AlpacaEntity, ButtonEntity):
    """Button to apply camera target settings simultaneously."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Apply Camera Settings"
        self._attr_unique_id = f"{super().unique_id}_apply_camera_settings"
        self._attr_icon = "mdi:content-save-cog"

    async def async_press(self) -> None:
        """Handle the button press."""
        target_dict = self.coordinator.target_group(self.dev_key, "camera")
        if not target_dict:
            LOGGER.debug("Camera %s: no target settings to apply", self.dev_key)
            return

        prop_cased = {
            "binx": "BinX", "biny": "BinY", "gain": "Gain", "offset": "Offset",
            "setccdtemperature": "SetCCDTemperature", "numx": "NumX", "numy": "NumY",
            "startx": "StartX", "starty": "StartY", "readoutmode": "ReadoutMode"
        }

        for prop, value in list(target_dict.items()):
            formatted_val = f"{value:.2f}" if "temperature" in prop else str(int(value))
            p_case = prop_cased.get(prop, prop)
            LOGGER.debug("Camera %s: applying %s = %s", self.dev_key, p_case, formatted_val)
            # a failing command raises: the settings not applied yet stay entered
            await self.coordinator.send_command(
                self.dev_type, self.dev_num, prop.lower(),
                {p_case: formatted_val}
            )
            target_dict.pop(prop, None)  # applied

        await self.coordinator.async_refresh()

class AlpacaTelescopeApplySettingsButton(AlpacaEntity, ButtonEntity):
    """Button to apply telescope target settings simultaneously."""
    def __init__(self, coordinator, device):
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Apply Telescope Settings"
        self._attr_unique_id = f"{super().unique_id}_apply_telescope_settings"
        self._attr_icon = "mdi:content-save-cog"

    async def async_press(self) -> None:
        """Handle the button press."""
        target_dict = self.coordinator.target_group(self.dev_key, "telescope")
        if not target_dict:
            LOGGER.debug("Telescope %s: no target settings to apply", self.dev_key)
            return

        param_name_map = {
            "aperturearea": "ApertureArea",
            "aperturediameter": "ApertureDiameter",
            "focallength": "FocalLength",
            "sitelatitude": "SiteLatitude",
            "sitelongitude": "SiteLongitude",
            "siteelevation": "SiteElevation",
            "slewsettletime": "SlewSettleTime",
            "declinationrate": "DeclinationRate",
            "rightascensionrate": "RightAscensionRate",
            "guideratedeclination": "GuideRateDeclination",
            "guideraterightascension": "GuideRateRightAscension",
            "trackingrate": "TrackingRate"
        }

        for prop, value in list(target_dict.items()):
            param_name = param_name_map.get(prop)
            if not param_name:
                continue

            LOGGER.debug("Telescope %s: applying target %s = %s", self.dev_key, param_name, value)
            # a failing command raises: the settings not applied yet stay entered
            await self.coordinator.send_command(
                self.dev_type, self.dev_num, prop, {param_name: str(value)}
            )
            target_dict.pop(prop, None)  # applied

        await self.coordinator.async_refresh()

from homeassistant.components.number import NumberEntity, NumberMode

from .const import DOMAIN, LOGGER
from .base import AlpacaEntity

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the number platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device in coordinator.devices:
        dev_type = device["DeviceType"].lower()
        if dev_type == "switch":
            # Determine how many switches there are
            dev_key = f"switch_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            maxswitch = data.get("maxswitch", 0)
            
            for i in range(maxswitch):
                # We show writable analog switches as number entities
                if data.get(f"canwrite_{i}", True) and data.get(f"is_analog_{i}", False):
                    entities.append(AlpacaSwitchNumber(coordinator, device, i))
        elif dev_type == "covercalibrator":
            entities.append(AlpacaCalibratorNumber(coordinator, device))
        elif dev_type == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            
            # Target coordinate inputs for GoTo
            if caps.get("canslewasync"):
                targets_eq = [
                    {"key": "target_ra", "name": "Target RA", "min": 0.0, "max": 24.0, "step": 0.001, "unit": "h", "icon": "mdi:axis-x-rotate-clockwise"},
                    {"key": "target_dec", "name": "Target Dec", "min": -90.0, "max": 90.0, "step": 0.001, "unit": "°", "icon": "mdi:axis-y-rotate-clockwise"},
                ]
                for t in targets_eq:
                    entities.append(AlpacaTelescopeTargetNumber(coordinator, device, t))
                    
            if caps.get("canslewaltazasync"):
                targets_az = [
                    {"key": "target_alt", "name": "Target Alt", "min": 0.0, "max": 90.0, "step": 0.01, "unit": "°", "icon": "mdi:angle-acute"},
                    {"key": "target_az", "name": "Target Az", "min": 0.0, "max": 360.0, "step": 0.01, "unit": "°", "icon": "mdi:compass"},
                ]
                for t in targets_az:
                    entities.append(AlpacaTelescopeTargetNumber(coordinator, device, t))

            # Editable properties
            telescope_props = [
                {"prop": "aperturearea", "name": "Aperture Area", "min": 0.0, "max": 100.0, "step": 0.01, "unit": "m²", "icon": "mdi:circle-outline"},
                {"prop": "aperturediameter", "name": "Aperture Diameter", "min": 0.0, "max": 10.0, "step": 0.001, "unit": "m", "icon": "mdi:diameter-outline"},
                {"prop": "focallength", "name": "Focal Length", "min": 0.0, "max": 10.0, "step": 0.001, "unit": "m", "icon": "mdi:arrow-expand-horizontal"},
                {"prop": "sitelatitude", "name": "Site Latitude", "min": -90.0, "max": 90.0, "step": 0.0001, "unit": "°", "icon": "mdi:latitude"},
                {"prop": "sitelongitude", "name": "Site Longitude", "min": -180.0, "max": 180.0, "step": 0.0001, "unit": "°", "icon": "mdi:longitude"},
                {"prop": "siteelevation", "name": "Site Elevation", "min": -500.0, "max": 10000.0, "step": 1.0, "unit": "m", "icon": "mdi:elevation-rise"},
                {"prop": "slewsettletime", "name": "Slew Settle Time", "min": 0, "max": 120, "step": 1, "unit": "s", "icon": "mdi:timer-sand"},
            ]
            
            for p in telescope_props:
                if p["prop"] in data:
                    entities.append(AlpacaTelescopePropertyNumber(coordinator, device, p))
                    
            if caps.get("cansetdeclinationrate") and "declinationrate" in data:
                entities.append(AlpacaTelescopePropertyNumber(coordinator, device, 
                    {"prop": "declinationrate", "name": "Declination Rate", "min": -10.0, "max": 10.0, "step": 0.00001, "unit": "arcsec/s", "icon": "mdi:delta"}))
            if caps.get("cansetrightascensionrate")and "rightascensionrate" in data:
                entities.append(AlpacaTelescopePropertyNumber(coordinator, device, 
                    {"prop": "rightascensionrate", "name": "RA Rate", "min": -10.0, "max": 10.0, "step": 0.00001, "unit": "s/s", "icon": "mdi:delta"}))
                    
            if caps.get("cansetguiderates"):
                if "guideratedeclination" in data:
                    entities.append(AlpacaTelescopePropertyNumber(coordinator, device, 
                        {"prop": "guideratedeclination", "name": "Guide Rate Dec", "min": 0.0, "max": 5.0, "step": 0.00001, "unit": "°/s", "icon": "mdi:speedometer"}))
                if "guideraterightascension" in data:
                    entities.append(AlpacaTelescopePropertyNumber(coordinator, device, 
                        {"prop": "guideraterightascension", "name": "Guide Rate RA", "min": 0.0, "max": 5.0, "step": 0.00001, "unit": "°/s", "icon": "mdi:speedometer"}))
        elif dev_type == "rotator":
            dev_key = f"rotator_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            # Rotators always use MoveAbsolute for this integration number input
            if "position" in data:
                entities.append(AlpacaRotatorTargetNumber(coordinator, device))
                # Relative move and sync inputs
                entities.append(AlpacaRotatorVirtualNumber(
                    coordinator, device, "move_relative",
                    {"name": "Move (Relative)", "min": -360.0, "max": 360.0, "step": 0.1, "unit": "°", "icon": "mdi:rotate-right"},
                    default=0.0
                ))
                entities.append(AlpacaRotatorVirtualNumber(
                    coordinator, device, "sync_position",
                    {"name": "Sync Position", "min": 0.0, "max": 360.0, "step": 0.1, "unit": "°", "icon": "mdi:sync"},
                    default=0.0
                ))
        elif dev_type == "focuser":
            dev_key = f"focuser_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("absolute") and "position" in data:
                entities.append(AlpacaFocuserTargetNumber(coordinator, device))
        elif dev_type == "dome":
            dev_key = f"dome_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("cansetaltitude") and "altitude" in data:
                entities.append(AlpacaDomeTargetNumber(coordinator, device, "altitude", {"name": "Target Altitude", "min": 0.0, "max": 90.0, "icon": "mdi:angle-acute"}))
            if caps.get("cansetazimuth") and "azimuth" in data:
                entities.append(AlpacaDomeTargetNumber(coordinator, device, "azimuth", {"name": "Target Azimuth", "min": 0.0, "max": 360.0, "icon": "mdi:compass"}))
        elif dev_type == "camera":
            dev_key = f"camera_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})

            camera_numbers = {
                "binx": {"name": "Bin X", "icon": "mdi:arrow-collapse-horizontal", "min": 1, "max": getattr(caps, "get", lambda k: 4)("maxbinx") or 4},
                "biny": {"name": "Bin Y", "icon": "mdi:arrow-collapse-vertical", "min": 1, "max": getattr(caps, "get", lambda k: 4)("maxbiny") or 4},
                "gain": {"name": "Gain", "icon": "mdi:brightness-5", "min": getattr(caps, "get", lambda k: 0)("gainmin") or 0, "max": getattr(caps, "get", lambda k: 100)("gainmax") or 100},
                "offset": {"name": "Offset", "icon": "mdi:brightness-7", "min": getattr(caps, "get", lambda k: 0)("offsetmin") or 0, "max": getattr(caps, "get", lambda k: 100)("offsetmax") or 100},
                "setccdtemperature": {"name": "Target CCD Temp", "icon": "mdi:thermometer-minus", "min": -50, "max": 50},
                "numx": {"name": "Width (NumX)", "icon": "mdi:arrow-expand-horizontal", "min": 1, "max": 10000},
                "numy": {"name": "Height (NumY)", "icon": "mdi:arrow-expand-vertical", "min": 1, "max": 10000},
                "startx": {"name": "Start X", "icon": "mdi:arrow-right-bold", "min": 0, "max": 10000},
                "starty": {"name": "Start Y", "icon": "mdi:arrow-down-bold", "min": 0, "max": 10000},
            }

            if not caps.get("cansetccdtemperature", False):
                camera_numbers.pop("setccdtemperature", None)

            for prop, conf in camera_numbers.items():
                if prop in data or prop == "setccdtemperature": 
                    entities.append(AlpacaCameraPropertyNumber(coordinator, device, prop, conf))

            entities.append(AlpacaCameraExposureNumber(coordinator, device))

    if entities:
        async_add_entities(entities)

class AlpacaCalibratorNumber(AlpacaEntity, NumberEntity):
    """Number representation for CoverCalibrator brightness."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Brightness"
        self._attr_unique_id = f"{super().unique_id}_calibrator_bright"
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self):
        """Return the target brightness value."""
        data = self.coordinator.data.get(self.dev_key, {})
        return self.coordinator.get_target(self.dev_key, "target_brightness", data.get("brightness"))

    @property
    def native_min_value(self):
        """Return the minimum value."""
        return 0.0

    @property
    def native_max_value(self):
        """Return the maximum value."""
        return self.coordinator.data.get(self.dev_key, {}).get("maxbrightness", 255.0)

    @property
    def native_step(self):
        """Return the step value."""
        return 1.0

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value (stored locally)."""
        LOGGER.debug("Setting CoverCalibrator %s target brightness to %s via Number entity", self.dev_key, int(value))
        self.coordinator.set_target(self.dev_key, "target_brightness", value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Always make it available so the user can set brightness even if off
        # It will turn on the calibrator if they move the slider
        return super().available

class AlpacaSwitchNumber(AlpacaEntity, NumberEntity):
    """Number representation for analog switches."""

    def __init__(self, coordinator, device, switch_id):
        """Initialize."""
        super().__init__(coordinator, device)
        self.switch_id = switch_id
        
        name = self.coordinator.data.get(self.dev_key, {}).get(f"name_{switch_id}", f"Switch {switch_id}")
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{switch_id}_analog"
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self):
        """Return the state of the entity."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(f"switchvalue_{self.switch_id}")

    @property
    def native_min_value(self):
        """Return the minimum value."""
        return self.coordinator.data.get(self.dev_key, {}).get(f"min_{self.switch_id}", 0.0)

    @property
    def native_max_value(self):
        """Return the maximum value."""
        return self.coordinator.data.get(self.dev_key, {}).get(f"max_{self.switch_id}", 100.0)

    @property
    def native_step(self):
        """Return the step value."""
        return self.coordinator.data.get(self.dev_key, {}).get(f"step_{self.switch_id}", 1.0)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "setswitchvalue", 
            {"Id": str(self.switch_id), "Value": str(value)}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and f"switchvalue_{self.switch_id}" in self.coordinator.data.get(self.dev_key, {})


class AlpacaTelescopeTargetNumber(AlpacaEntity, NumberEntity):
    """Number entity for telescope GoTo target coordinates (input-only)."""

    def __init__(self, coordinator, device, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self._target_key = config["key"]
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{config['key']}"
        self._attr_icon = config["icon"]
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = config["step"]
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self):
        """Return the current target value."""
        return self.coordinator.get_target(self.dev_key, self._target_key)

    async def async_set_native_value(self, value: float) -> None:
        """Set the target value (kept by the coordinator for the slew buttons, not sent to the device)."""
        LOGGER.debug("Telescope %s: setting %s to %s", self.dev_key, self._target_key, value)
        self.coordinator.set_target(self.dev_key, self._target_key, value)
        self.async_write_ha_state()

class AlpacaTelescopePropertyNumber(AlpacaEntity, NumberEntity):
    """Number entity for writable telescope properties."""

    def __init__(self, coordinator, device, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = config["prop"]
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{self.prop}_input"
        self._attr_icon = config["icon"]
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = config["step"]
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self):
        """Return the target or current property value."""
        data = self.coordinator.data.get(self.dev_key, {})
        target_dict = self.coordinator.target_group(self.dev_key, "telescope")
        return target_dict.get(self.prop, data.get(self.prop))

    async def async_set_native_value(self, value: float) -> None:
        """Set the target property value locally."""
        LOGGER.debug("Telescope %s: storing target %s = %s", self.dev_key, self.prop, value)
        self.coordinator.target_group(self.dev_key, "telescope")[self.prop] = value
        self.async_write_ha_state()
            
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaCameraPropertyNumber(AlpacaEntity, NumberEntity):
    """Number entity for writable camera properties."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]
        self._attr_mode = NumberMode.BOX
        
        self._fallback_min = config.get("min", 0)
        self._fallback_max = config.get("max", 10000)

    @property
    def native_min_value(self) -> float:
        """Return dynamic min value if available."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        if self.prop == "gain":
            val = data.get("gainmin")
            return float(val) if val is not None else float(caps.get("gainmin", self._fallback_min))
        if self.prop == "offset":
            val = data.get("offsetmin")
            return float(val) if val is not None else float(caps.get("offsetmin", self._fallback_min))
        if self.prop in ("binx", "biny"):
            return 1.0
        return self._fallback_min

    @property
    def native_max_value(self) -> float:
        """Return dynamic max value if available."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        if self.prop == "gain":
            val = data.get("gainmax")
            return float(val) if val is not None else float(caps.get("gainmax", self._fallback_max))
        if self.prop == "offset":
            val = data.get("offsetmax")
            return float(val) if val is not None else float(caps.get("offsetmax", self._fallback_max))
        if self.prop == "binx":
            val = data.get("maxbinx")
            return float(val) if val is not None else float(caps.get("maxbinx", self._fallback_max))
        if self.prop == "biny":
            val = data.get("maxbiny")
            return float(val) if val is not None else float(caps.get("maxbiny", self._fallback_max))
        return self._fallback_max

    @property
    def native_value(self) -> float | None:
        """Return the target or current property value."""
        data = self.coordinator.data.get(self.dev_key, {})
        target_dict = self.coordinator.target_group(self.dev_key, "camera")
        return target_dict.get(self.prop, data.get(self.prop))

    async def async_set_native_value(self, value: float) -> None:
        """Store the property value locally."""
        LOGGER.debug("Camera %s: storing target %s = %s", self.dev_key, self.prop, value)
        self.coordinator.target_group(self.dev_key, "camera")[self.prop] = value
        self.async_write_ha_state()

    @property
    def native_step(self) -> float | None:
        """Return the step value."""
        return 0.1 if "temperature" in self.prop else 1.0

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Because we might not fetch it immediately, assume available if device is available.
        return super().available

class AlpacaRotatorTargetNumber(AlpacaEntity, NumberEntity):
    """Number entity for rotator target angle."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Target Angle"
        self._attr_unique_id = f"{super().unique_id}_target_angle"
        self._attr_icon = "mdi:rotate-right-variant"
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 360.0
        
        data = self.coordinator.data.get(self.dev_key, {})
        step = data.get("stepsize", 0.1)
        self._attr_native_step = step if step > 0 else 0.1
        
        self._attr_native_unit_of_measurement = "°"
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self):
        """Return the target position."""
        data = self.coordinator.data.get(self.dev_key, {})
        return self.coordinator.get_target(self.dev_key, "rotator_target_position", data.get("position"))

    async def async_set_native_value(self, value: float) -> None:
        """Set the target position locally."""
        self.coordinator.set_target(self.dev_key, "rotator_target_position", value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})


class AlpacaRotatorVirtualNumber(AlpacaEntity, NumberEntity):
    """A virtual number input for the rotator (relative move or sync position).

    The value is kept by the coordinator (targets[dev_key][key]) and read by
    the corresponding button to execute the command.
    """

    def __init__(self, coordinator, device, key: str, config: dict, default: float = 0.0):
        """Initialize."""
        super().__init__(coordinator, device)
        self._key = key
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{key}"
        self._attr_icon = config["icon"]
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = config.get("step", 1.0)
        self._attr_native_unit_of_measurement = config.get("unit", "°")
        self._attr_mode = NumberMode.BOX
        self._default = default

    @property
    def native_value(self) -> float:
        """Return the stored value."""
        return self.coordinator.get_target(self.dev_key, self._key, self._default)

    async def async_set_native_value(self, value: float) -> None:
        """Store the value for the action button to use."""
        LOGGER.debug("Rotator %s: storing %s = %s", self.dev_key, self._key, value)
        self.coordinator.set_target(self.dev_key, self._key, value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})


class AlpacaFocuserTargetNumber(AlpacaEntity, NumberEntity):
    """Number representation for Focuser absolute position."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Target Position"
        self._attr_unique_id = f"{super().unique_id}_targetposition"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = "mdi:bullseye-arrow"

    @property
    def native_value(self):
        """Return the target position."""
        data = self.coordinator.data.get(self.dev_key, {})
        return self.coordinator.get_target(self.dev_key, "focuser_target_position", data.get("position"))

    @property
    def native_min_value(self):
        """Return the minimum value."""
        return 0.0

    @property
    def native_max_value(self):
        """Return the maximum value."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        return caps.get("maxstep", 100000.0)

    @property
    def native_step(self):
        """Return the step value."""
        return 1.0

    async def async_set_native_value(self, value: float) -> None:
        """Update the target position locally."""
        self.coordinator.set_target(self.dev_key, "focuser_target_position", value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})

class AlpacaDomeTargetNumber(AlpacaEntity, NumberEntity):
    """Number representation for Dome target altitude/azimuth."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_target_{prop}"
        self._attr_mode = NumberMode.BOX
        self._attr_icon = config["icon"]
        self._attr_native_min_value = config["min"]
        self._attr_native_max_value = config["max"]
        self._attr_native_step = 0.1
        self._attr_native_unit_of_measurement = "°"

    @property
    def native_value(self):
        """Return the target position."""
        data = self.coordinator.data.get(self.dev_key, {})
        return self.coordinator.get_target(self.dev_key, f"dome_target_{self.prop}", data.get(self.prop))

    async def async_set_native_value(self, value: float) -> None:
        """Set the target position locally."""
        self.coordinator.set_target(self.dev_key, f"dome_target_{self.prop}", value)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaCameraExposureNumber(AlpacaEntity, NumberEntity):
    """Number entity for target exposure duration logic."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = "target_exposure"
        self._attr_name = f"{self._device_name} Target Exposure Duration"
        self._attr_unique_id = f"{super().unique_id}_target_exposure"
        self._attr_icon = "mdi:timer"
        self._attr_mode = NumberMode.BOX
        self._attr_native_unit_of_measurement = "s"

    @property
    def native_value(self) -> float:
        """Return the target exposure value."""
        return self.coordinator.get_target(self.dev_key, self.prop, 1.0)

    @property
    def native_min_value(self) -> float:
        """Return dynamic min exposure."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        val = data.get("exposuremin")
        if val is not None:
            return float(val)
        return float(caps.get("exposuremin", 0.001) or 0.001)

    @property
    def native_max_value(self) -> float:
        """Return dynamic max exposure."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        val = data.get("exposuremax")
        if val is not None:
            return float(val)
        return float(caps.get("exposuremax", 3600.0) or 3600.0)

    async def async_set_native_value(self, value: float) -> None:
        """Set the exposure value."""
        self.coordinator.set_target(self.dev_key, self.prop, float(value))
        self.async_write_ha_state()

    @property
    def native_step(self) -> float:
        """Step resolution."""
        if self.native_min_value < 1.0:
            return 0.1
        return 1.0
        
    @property
    def available(self) -> bool:
        """Check availability."""
        return super().available

"""Switch platform for Alpaca Bridge."""
from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN, LOGGER
from .base import AlpacaEntity

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the switch platform."""
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
                if data.get(f"canwrite_{i}", True) and not data.get(f"is_analog_{i}", False):
                    entities.append(AlpacaSwitch(coordinator, device, i))
        elif dev_type == "covercalibrator":
            entities.append(AlpacaCalibratorSwitch(coordinator, device))
        elif dev_type == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("cansettracking"):
                entities.append(AlpacaTelescopeTrackingSwitch(coordinator, device))
            if "doesrefraction" in data:
                entities.append(AlpacaTelescopePropertySwitch(coordinator, device, "doesrefraction", "Does Refraction", "mdi:theme-light-dark"))
        elif dev_type == "camera":
            dev_key = f"camera_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            
            entities.append(AlpacaCameraLightSwitch(coordinator, device))
            if "cooleron" in data:
                entities.append(AlpacaCameraPropertySwitch(coordinator, device, "cooleron", "Cooler", "mdi:snowflake"))
            if "fastreadout" in data and caps.get("canfastreadout", False):
                entities.append(AlpacaCameraPropertySwitch(coordinator, device, "fastreadout", "Fast Readout", "mdi:speedometer"))
        elif dev_type == "rotator":
            dev_key = f"rotator_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("canreverse") and "reverse" in data:
                entities.append(AlpacaRotatorReverseSwitch(coordinator, device))
        elif dev_type == "focuser":
            dev_key = f"focuser_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("tempcompavailable") and "tempcomp" in data:
                entities.append(AlpacaFocuserTempCompSwitch(coordinator, device))
        elif dev_type == "dome":
            dev_key = f"dome_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("canslave") and "slaved" in data:
                entities.append(AlpacaDomeSlavedSwitch(coordinator, device))

    if entities:
        async_add_entities(entities)


class AlpacaCalibratorSwitch(AlpacaEntity, SwitchEntity):
    """Switch representation for CoverCalibrator power."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Calibrator"
        self._attr_unique_id = f"{super().unique_id}_calibrator_power"

    @property
    def is_on(self):
        """Return true if the calibrator is on."""
        data = self.coordinator.data.get(self.dev_key, {})
        # ASCOM CalibratorStatus: 0=NotPresent, 1=Off, 2=NotReady, 3=Ready, 4=Unknown, 5=Error
        cal_state = data.get("calibratorstate")
        LOGGER.debug("Calibrator %s state raw=%s", self.dev_key, cal_state)
        if cal_state is None:
            return None
        return cal_state in (2, 3)  # NotReady or Ready means on

    async def async_turn_on(self, **kwargs):
        """Turn on the calibrator."""
        LOGGER.info("async_turn_on called for Calibrator %s", self.dev_key)
        data = self.coordinator.data.get(self.dev_key, {})
        max_brightness = data.get("maxbrightness", 255)
        # In ASCOM, CalibratorOn requires a brightness > 0
        brightness = data.get("brightness", max_brightness)
        LOGGER.debug("Calibrator %s current brightness=%s, max=%s", self.dev_key, brightness, max_brightness)
        # If the user previously set it to 0 and turned it off, turning it back on should use 50%
        if not brightness or brightness <= 0:
            brightness = max(1, int(max_brightness / 2.0))
            
        LOGGER.info("CalibratorOn %s brightness=%s", self.dev_key, brightness)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "calibratoron",
            {"Brightness": str(int(brightness))}
        )
        LOGGER.info("CalibratorOn %s result=%s", self.dev_key, success)
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn off the calibrator."""
        LOGGER.info("CalibratorOff %s", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "calibratoroff"
        )
        LOGGER.info("CalibratorOff %s result=%s", self.dev_key, success)
        if success:
            await self.coordinator.async_refresh()


class AlpacaSwitch(AlpacaEntity, SwitchEntity):
    """Switch representation."""

    def __init__(self, coordinator, device, switch_id):
        """Initialize."""
        super().__init__(coordinator, device)
        self.switch_id = switch_id
        
        name = self.coordinator.data.get(self.dev_key, {}).get(f"name_{switch_id}", f"Switch {switch_id}")
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{switch_id}"

    @property
    def is_on(self):
        """Return true if switch is on."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(f"switch_{self.switch_id}")

    async def async_turn_on(self, **kwargs):
        """Turn the entity on."""
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "setswitch", 
            {"Id": str(self.switch_id), "State": "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the entity off."""
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "setswitch", 
            {"Id": str(self.switch_id), "State": "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and f"switch_{self.switch_id}" in self.coordinator.data.get(self.dev_key, {})


class AlpacaTelescopeTrackingSwitch(AlpacaEntity, SwitchEntity):
    """Switch for telescope tracking on/off."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Tracking"
        self._attr_unique_id = f"{super().unique_id}_tracking"
        self._attr_icon = "mdi:crosshairs-gps"

    @property
    def is_on(self):
        """Return true if tracking is on."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get("tracking")

    async def async_turn_on(self, **kwargs):
        """Enable tracking."""
        LOGGER.debug("Telescope %s: tracking on", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "tracking",
            {"Tracking": "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Disable tracking."""
        LOGGER.debug("Telescope %s: tracking off", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "tracking",
            {"Tracking": "False"}
        )
        if success:
            await self.coordinator.async_refresh()

class AlpacaTelescopePropertySwitch(AlpacaEntity, SwitchEntity):
    """Switch for writable telescope boolean properties."""

    def __init__(self, coordinator, device, prop, name, icon):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{prop}_switch"
        self._attr_icon = icon

    @property
    def is_on(self):
        """Return true if property is true."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(self.prop)

    async def async_turn_on(self, **kwargs):
        """Set property to true."""
        LOGGER.debug("Telescope %s: setting %s to True", self.dev_key, self.prop)
        
        param_name_map = {
            "doesrefraction": "DoesRefraction"
        }
        param_name = param_name_map.get(self.prop)
        
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, self.prop,
            {param_name: "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Set property to false."""
        LOGGER.debug("Telescope %s: setting %s to False", self.dev_key, self.prop)
        
        param_name_map = {
            "doesrefraction": "DoesRefraction"
        }
        param_name = param_name_map.get(self.prop)
        
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, self.prop,
            {param_name: "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})

class AlpacaCameraPropertySwitch(AlpacaEntity, SwitchEntity):
    """Switch for writable camera boolean properties."""

    def __init__(self, coordinator, device, prop, name, icon):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        """Return true if property is true."""
        return bool(self.coordinator.data.get(self.dev_key, {}).get(self.prop))

    async def async_turn_on(self, **kwargs) -> None:
        """Set property to true."""
        # Use proper casing for Alpaca API payload: CoolerOn, FastReadout
        prop_cased = "CoolerOn" if self.prop == "cooleron" else "FastReadout"
        success = await self.coordinator.send_command(
            self.dev_type,
            self.dev_num,
            self.prop,
            {prop_cased: "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Set property to false."""
        prop_cased = "CoolerOn" if self.prop == "cooleron" else "FastReadout"
        success = await self.coordinator.send_command(
            self.dev_type,
            self.dev_num,
            self.prop,
            {prop_cased: "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.coordinator.data.get(self.dev_key, {}).get(self.prop) is not None

class AlpacaCameraLightSwitch(AlpacaEntity, SwitchEntity):
    """Light (on) or dark (off) frame for the "Start Exposure" button."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Light Frame"
        self._attr_unique_id = f"{super().unique_id}_exposure_light"
        self._attr_icon = "mdi:white-balance-sunny"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.get_target(self.dev_key, "exposure_light", True))

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.set_target(self.dev_key, "exposure_light", True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.set_target(self.dev_key, "exposure_light", False)
        self.async_write_ha_state()


class AlpacaRotatorReverseSwitch(AlpacaEntity, SwitchEntity):
    """Switch for rotator reverse direction."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Reverse"
        self._attr_unique_id = f"{super().unique_id}_reverse"
        self._attr_icon = "mdi:swap-horizontal"

    @property
    def is_on(self):
        """Return true if reverse flag is active."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get("reverse")

    async def async_turn_on(self, **kwargs):
        """Enable reverse."""
        LOGGER.debug("Rotator %s: setting Reverse to True", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "reverse",
            {"Reverse": "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Disable reverse."""
        LOGGER.debug("Rotator %s: setting Reverse to False", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "reverse",
            {"Reverse": "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "reverse" in self.coordinator.data.get(self.dev_key, {})

class AlpacaFocuserTempCompSwitch(AlpacaEntity, SwitchEntity):
    """Switch for focuser temperature compensation."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Temp Comp"
        self._attr_unique_id = f"{super().unique_id}_tempcomp"
        self._attr_icon = "mdi:thermometer-auto"

    @property
    def is_on(self):
        """Return true if temp comp is active."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get("tempcomp")

    async def async_turn_on(self, **kwargs):
        """Enable temp comp."""
        LOGGER.debug("Focuser %s: setting TempComp to True", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "tempcomp",
            {"TempComp": "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Disable temp comp."""
        LOGGER.debug("Focuser %s: setting TempComp to False", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "tempcomp",
            {"TempComp": "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "tempcomp" in self.coordinator.data.get(self.dev_key, {})

class AlpacaDomeSlavedSwitch(AlpacaEntity, SwitchEntity):
    """Switch for dome slaved setting."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Slaved"
        self._attr_unique_id = f"{super().unique_id}_slaved"
        self._attr_icon = "mdi:link-variant"

    @property
    def is_on(self):
        """Return true if dome is slaved."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get("slaved")

    async def async_turn_on(self, **kwargs):
        """Enable slaved mode."""
        LOGGER.debug("Dome %s: setting Slaved to True", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "slaved",
            {"Slaved": "True"}
        )
        if success:
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        """Disable slaved mode."""
        LOGGER.debug("Dome %s: setting Slaved to False", self.dev_key)
        success = await self.coordinator.send_command(
            self.dev_type, self.dev_num, "slaved",
            {"Slaved": "False"}
        )
        if success:
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "slaved" in self.coordinator.data.get(self.dev_key, {})

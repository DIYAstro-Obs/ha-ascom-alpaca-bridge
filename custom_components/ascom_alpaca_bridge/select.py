from homeassistant.components.select import SelectEntity

from .const import DOMAIN, LOGGER
from .base import AlpacaEntity

TRACKING_RATES = {
    0: "Sidereal",
    1: "Lunar",
    2: "Solar",
    3: "King",
}
TRACKING_RATES_REVERSE = {v: k for k, v in TRACKING_RATES.items()}

def _unique_names(names):
    """The filter names, made unique: the same name twice becomes "Empty" and "Empty (2)", so each one can be
    selected."""
    seen = {}
    result = []
    for name in (str(n) for n in names):
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return result




async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the select platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("cansettracking"):
                entities.append(AlpacaTelescopeTrackingRateSelect(coordinator, device))
        elif device["DeviceType"].lower() == "filterwheel":
            dev_key = f"filterwheel_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "names" in data and "position" in data:
                entities.append(AlpacaFilterWheelSelect(coordinator, device))
        elif device["DeviceType"].lower() == "camera":
            dev_key = f"camera_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            if caps.get("readoutmodes") and "readoutmode" in data:
                entities.append(AlpacaCameraReadoutModeSelect(coordinator, device))

    if entities:
        async_add_entities(entities)


class AlpacaTelescopeTrackingRateSelect(AlpacaEntity, SelectEntity):
    """Select entity for telescope tracking rate."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Tracking Rate"
        self._attr_unique_id = f"{super().unique_id}_trackingrate"
        self._attr_icon = "mdi:speedometer"
        self._attr_options = list(TRACKING_RATES.values())

    @property
    def current_option(self) -> str | None:
        """Return the target or current tracking rate."""
        data = self.coordinator.data.get(self.dev_key, {})
        target_dict = self.coordinator.target_group(self.dev_key, "telescope")
        rate = target_dict.get("trackingrate", data.get("trackingrate"))
        if rate is None:
            return None
        return TRACKING_RATES.get(rate, f"Unknown ({rate})")

    async def async_select_option(self, option: str) -> None:
        """Store the tracking rate locally."""
        rate = TRACKING_RATES_REVERSE.get(option)
        if rate is None:
            LOGGER.error("Unknown tracking rate: %s", option)
            return

        LOGGER.debug("Telescope %s: storing target tracking rate to %s (%s)", self.dev_key, option, rate)
        self.coordinator.target_group(self.dev_key, "telescope")["trackingrate"] = rate
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available (only when tracking is on)."""
        data = self.coordinator.data.get(self.dev_key, {})
        tracking = data.get("tracking")
        return super().available and tracking is True

class AlpacaFilterWheelSelect(AlpacaEntity, SelectEntity):
    """Select entity for filter wheel position."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Filter"
        self._attr_unique_id = f"{super().unique_id}_filter"
        self._attr_icon = "mdi:camera-iris"

    @property
    def options(self) -> list[str]:
        """Return the list of available filter names dynamically."""
        data = self.coordinator.data.get(self.dev_key, {})
        names = data.get("names", [])
        if not names:
            return [str(i) for i in range(10)]
        return _unique_names(names)

    @property
    def current_option(self) -> str | None:
        """Return the target or current filter name."""
        data = self.coordinator.data.get(self.dev_key, {})
        pos = self.coordinator.get_target(self.dev_key, "target_position", data.get("position"))
        opts = self.options
        if pos is None or pos < 0 or pos >= len(opts):
            return None # -1 means moving
        return opts[pos]

    async def async_select_option(self, option: str) -> None:
        """Store the filter position via index locally."""
        try:
            pos = self.options.index(option)
        except ValueError:
            LOGGER.error("Unknown filter name: %s", option)
            return
            
        LOGGER.debug("FilterWheel %s: storing target position to %s (%s)", self.dev_key, pos, option)
        self.coordinator.set_target(self.dev_key, "target_position", pos)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})
        
    @property
    def extra_state_attributes(self):
        """Return focus offsets as attributes if available."""
        data = self.coordinator.data.get(self.dev_key, {})
        offsets = data.get("focusoffsets", [])
        if offsets:
            return {"focus_offsets": offsets}
        return {}


class AlpacaCameraReadoutModeSelect(AlpacaEntity, SelectEntity):
    """Select entity for camera readout mode."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Readout Mode"
        self._attr_unique_id = f"{super().unique_id}_readoutmode"
        self._attr_icon = "mdi:camera-control"

    @property
    def options(self) -> list[str]:
        """Return the list of available readout modes dynamically."""
        data = self.coordinator.data.get(self.dev_key, {})
        caps = data.get("capabilities", {})
        modes = caps.get("readoutmodes", [])
        return [str(m) for m in modes]

    @property
    def current_option(self) -> str | None:
        """Return the target or current readout mode."""
        data = self.coordinator.data.get(self.dev_key, {})
        target_dict = self.coordinator.target_group(self.dev_key, "camera")
        rmode = target_dict.get("readoutmode", data.get("readoutmode"))
        opts = self.options
        if rmode is None or rmode < 0 or rmode >= len(opts):
            return None
        return opts[rmode]

    async def async_select_option(self, option: str) -> None:
        """Store the readout mode via index locally."""
        try:
            rmode = self.options.index(option)
        except ValueError:
            LOGGER.error("Unknown readout mode: %s", option)
            return
            
        LOGGER.debug("Camera %s: storing target readout mode to %s (%s)", self.dev_key, rmode, option)
        self.coordinator.target_group(self.dev_key, "camera")["readoutmode"] = rmode
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "readoutmode" in self.coordinator.data.get(self.dev_key, {})

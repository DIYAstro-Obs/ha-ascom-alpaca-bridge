"""Cover platform for Alpaca Bridge."""
from homeassistant.components.cover import CoverEntity, CoverDeviceClass, CoverEntityFeature

from .const import DOMAIN
from .base import AlpacaEntity

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the cover platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for device in coordinator.devices:
        dev_type = device["DeviceType"].lower()
        if dev_type == "dome" or dev_type == "covercalibrator":
            entities.append(AlpacaCover(coordinator, device))

    if entities:
        async_add_entities(entities)

class AlpacaCover(AlpacaEntity, CoverEntity):
    """Cover representation.

    Dome (roll-off roof), ASCOM ShutterState: 0=Open, 1=Closed, 2=Opening, 3=Closing, 4=Error.
    CoverCalibrator, ASCOM CoverStatus: 0=NotPresent, 1=Closed, 2=Moving, 3=Open, 4=Unknown, 5=Error.
    An error or unknown status is reported as "unknown" (is_closed None), never as "open".
    """

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name}"
        self._attr_unique_id = f"{super().unique_id}_cover"
        self._attr_device_class = CoverDeviceClass.AWNING
        self._is_dome = self.dev_type.lower() == "dome"

        # A CoverCalibrator only reports "moving". The direction is the opposite of the last settled position.
        status = self._get_status()
        self._last_settled = status if status in (1, 3) else None

    @property
    def supported_features(self):
        """Open / close only when the device can do it; stop for a dome."""
        data = self.coordinator.data.get(self.dev_key, {})
        features = CoverEntityFeature(0)
        if self._is_dome:
            if data.get("capabilities", {}).get("cansetshutter"):
                features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
            features |= CoverEntityFeature.STOP
        elif data.get("coverstate") != 0:  # 0 = NotPresent: a calibrator without cover
            features |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        return features

    def _get_status(self):
        """Get the cover/shutter status value."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get("shutterstatus" if self._is_dome else "coverstate")

    def _handle_coordinator_update(self):
        status = self._get_status()
        if status in (1, 3):
            self._last_settled = status
        super()._handle_coordinator_update()

    @property
    def is_closed(self):
        """Return if the cover is closed; None when it is not known (error, unknown, not present, moving)."""
        status = self._get_status()
        if status == 1:
            return True
        if self._is_dome:
            return False if status in (0, 2, 3) else None
        return False if status == 3 else None

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        status = self._get_status()
        if self._is_dome:
            return status == 2
        return status == 2 and self._last_settled == 1

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        status = self._get_status()
        if self._is_dome:
            return status == 3
        return status == 2 and self._last_settled == 3

    async def async_open_cover(self, **kwargs):
        """Open the cover."""
        cmd = "openshutter" if self._is_dome else "opencover"
        await self.coordinator.send_command(self.dev_type, self.dev_num, cmd)
        await self.coordinator.async_refresh()

    async def async_close_cover(self, **kwargs):
        """Close the cover."""
        cmd = "closeshutter" if self._is_dome else "closecover"
        await self.coordinator.send_command(self.dev_type, self.dev_num, cmd)
        await self.coordinator.async_refresh()

    async def async_stop_cover(self, **kwargs):
        """Stop the cover."""
        if self._is_dome:
            await self.coordinator.send_command(self.dev_type, self.dev_num, "abortslew")
            await self.coordinator.async_refresh()
        else:
            await self.coordinator.send_command(self.dev_type, self.dev_num, "haltcover")
            await self.coordinator.async_refresh()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        data = self.coordinator.data.get(self.dev_key, {})
        return super().available and ("shutterstatus" if self._is_dome else "coverstate") in data

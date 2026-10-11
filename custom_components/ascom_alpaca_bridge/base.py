"""Base entity for Alpaca Bridge."""
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo

from .coordinator import AlpacaDataUpdateCoordinator
from .const import DOMAIN


class AlpacaEntity(CoordinatorEntity):
    """Base class for Alpaca entities."""

    def __init__(
        self,
        coordinator: AlpacaDataUpdateCoordinator,
        device: dict,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.device = device
        self.dev_type = device["DeviceType"]
        self.dev_num = device["DeviceNumber"]
        self.dev_key = f"{self.dev_type.lower()}_{self.dev_num}"
        
        # The Alpaca UniqueId can be missing, generic or shared by several devices: the coordinator decides
        uid = coordinator.device_uid(device)

        self._device_uid = uid
        self._attr_unique_id = uid
        
        # Attempt to get a friendly name
        name = device.get("DeviceName")
        if not name:
             name = f"Alpaca {self.dev_type} {self.dev_num}"
             
        self._device_name = name
        self._server_name = device.get("ServerName", "Alpaca Server")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information for this entity."""
        data = self.coordinator.data.get(self.dev_key, {})
        version = data.get("driverversion")
        
        sw_version = self._server_name
        if version and version != "Unknown":
            sw_version = f"{self._server_name} (Driver v{version})"

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_uid)},
            name=self._device_name,
            manufacturer="ASCOM Alpaca",
            model=self.dev_type,
            sw_version=sw_version,
            configuration_url=f"http://{self.coordinator.host}:{self.coordinator.port}"
        )

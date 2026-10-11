"""Sensor platform for Alpaca Bridge."""
import logging
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfSpeed,
)

from .const import DOMAIN
from .base import AlpacaEntity

LOGGER = logging.getLogger(__package__)

def _identity_map(value):
    return value

ALIGNMENT_MODE_MAP = {

    0: "AltAz",
    1: "Polar",
    2: "GermanPolar",
}

EQUATORIAL_SYSTEM_MAP = {
    0: "Other",
    1: "Topocentric (JNow)",
    2: "J2000",
    3: "J2050",
    4: "B1950",
}

PIER_SIDE_MAP = {
    0: "East",
    1: "West",
    -1: "Unknown",
}

TRACKING_RATES_MAP = {
    0: "Sidereal",
    1: "Lunar",
    2: "Solar",
    3: "King",
}

CAMERA_STATE_MAP = {
    0: "Idle",
    1: "Waiting",
    2: "Exposing",
    3: "Reading",
    4: "Download",
    5: "Error",
}

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "observingconditions":
            properties = {
                "cloudcover": {"name": "Cloud Cover", "device_class": None, "unit": PERCENTAGE, "icon": "mdi:cloud", "precision": 1},
                "dewpoint": {"name": "Dew Point", "device_class": SensorDeviceClass.TEMPERATURE, "unit": UnitOfTemperature.CELSIUS, "icon": "mdi:thermometer-water", "precision": 1},
                "humidity": {"name": "Humidity", "device_class": SensorDeviceClass.HUMIDITY, "unit": PERCENTAGE, "icon": "mdi:water-percent", "precision": 1},
                "pressure": {"name": "Pressure", "device_class": SensorDeviceClass.PRESSURE, "unit": UnitOfPressure.HPA, "icon": "mdi:gauge", "precision": 1},
                "temperature": {"name": "Temperature", "device_class": SensorDeviceClass.TEMPERATURE, "unit": UnitOfTemperature.CELSIUS, "icon": "mdi:thermometer", "precision": 1},
                "windspeed": {"name": "Wind Speed", "device_class": SensorDeviceClass.WIND_SPEED, "unit": UnitOfSpeed.METERS_PER_SECOND, "icon": "mdi:weather-windy", "precision": 1},
                "windgust": {"name": "Wind Gust", "device_class": SensorDeviceClass.WIND_SPEED, "unit": UnitOfSpeed.METERS_PER_SECOND, "icon": "mdi:weather-windy-variant", "precision": 1},
                "winddirection": {"name": "Wind Direction", "device_class": None, "unit": "°", "icon": "mdi:compass", "precision": 0},
                "rainrate": {"name": "Rain Rate", "device_class": None, "unit": "mm/h", "icon": "mdi:weather-rainy", "precision": 2},
                "starfwhm": {"name": "Star FWHM", "device_class": None, "unit": "arcsec", "icon": "mdi:star", "precision": 2},
                "skybrightness": {"name": "Sky Brightness", "device_class": None, "unit": "lux", "icon": "mdi:brightness-5", "precision": 2},
                "skyquality": {"name": "Sky Quality", "device_class": None, "unit": "mag/arcsec²", "icon": "mdi:star-shooting", "precision": 2},
                "skytemperature": {"name": "Sky Temperature", "device_class": SensorDeviceClass.TEMPERATURE, "unit": UnitOfTemperature.CELSIUS, "icon": "mdi:thermometer-lines", "precision": 1},
            }
            
            dev_key = f"observingconditions_{device['DeviceNumber']}"
            for prop, config in properties.items():
                # Only create entity if the device actually supports this property
                if prop in coordinator.data.get(dev_key, {}):
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, prop, config))
                
        elif device["DeviceType"].lower() == "switch":
            dev_key = f"switch_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            maxswitch = data.get("maxswitch", 0)
            for i in range(maxswitch):
                if not data.get(f"canwrite_{i}", True) and data.get(f"is_analog_{i}", False):
                    entities.append(AlpacaSwitchValueSensor(coordinator, device, i))

        elif device["DeviceType"].lower() == "filterwheel":
            dev_key = f"filterwheel_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            if "position" in data:
                entities.append(AlpacaFilterWheelSensor(coordinator, device))
                if data.get("focusoffsets"):
                    entities.append(AlpacaFilterWheelOffsetSensor(coordinator, device))
        
        elif device["DeviceType"].lower() == "camera":
            # State sensor
            entities.append(AlpacaTelescopeTextSensor(
                coordinator, device, "camerastate",
                {"name": "Camera State", "icon": "mdi:camera-iris", "mapper": CAMERA_STATE_MAP.get}
            ))
            
            # Numeric sensors
            numeric_props = {
                "ccdtemperature": {"name": "CCD Temperature", "unit": UnitOfTemperature.CELSIUS, "class": SensorDeviceClass.TEMPERATURE},
                "heatsinktemperature": {"name": "Heatsink Temperature", "unit": UnitOfTemperature.CELSIUS, "class": SensorDeviceClass.TEMPERATURE},
                "coolerpower": {"name": "Cooler Power", "unit": PERCENTAGE, "class": SensorDeviceClass.POWER_FACTOR},
                "percentcompleted": {"name": "Exposure Progress", "unit": PERCENTAGE, "class": None},
                "electronsperadu": {"name": "Electrons per ADU", "unit": "e-/ADU", "class": None},
                "fullwellcapacity": {"name": "Full Well Capacity", "unit": "e-", "class": None},
                "maxadu": {"name": "Max ADU", "unit": "ADU", "class": None},
                "pixelsizex": {"name": "Pixel Size X", "unit": "µm", "class": None},
                "pixelsizey": {"name": "Pixel Size Y", "unit": "µm", "class": None},
            }
            
            for prop, conf in numeric_props.items():
                entities.append(AlpacaObservingConditionSensor(
                    coordinator, device, prop,
                    {
                        "name": conf["name"],
                        "icon": "mdi:chart-bell-curve" if "adu" in prop else "mdi:camera-outline",
                        "unit": conf["unit"],
                        "device_class": conf["class"],
                    }
                ))

        elif device["DeviceType"].lower() == "telescope":
            dev_key = f"telescope_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            caps = data.get("capabilities", {})
            
            telescope_props = {
                "rightascension": {"name": "Right Ascension", "icon": "mdi:axis-x-rotate-clockwise", "format": "hms"},
                "declination": {"name": "Declination", "icon": "mdi:axis-y-rotate-clockwise", "format": "dms"},
                "altitude": {"name": "Altitude", "icon": "mdi:angle-acute", "format": "dms"},
                "azimuth": {"name": "Azimuth", "icon": "mdi:compass", "format": "dms"},
                "siderealtime": {"name": "Sidereal Time", "icon": "mdi:clock-star-four-points", "format": "hms"},
            }
            for prop, config in telescope_props.items():
                if prop in data:
                    entities.append(AlpacaTelescopeCoordSensor(coordinator, device, prop, config))
                    
            text_props = {
                "alignmentmode": {"name": "Alignment Mode", "icon": "mdi:axis-arrow", "mapper": ALIGNMENT_MODE_MAP.get},
                "equatorialsystem": {"name": "Equatorial System", "icon": "mdi:earth", "mapper": EQUATORIAL_SYSTEM_MAP.get},
                # sideofpier: shown as select in select.py when cansetpierside=True;
                # kept here for read-only mounts (cansetpierside=False)
                "sideofpier": {"name": "Side of Pier", "icon": "mdi:scale-balance", "mapper": PIER_SIDE_MAP.get},
                # trackingrate is handled by select.py (R/W) — no need for a separate sensor
                "utcdate": {"name": "UTC Date", "icon": "mdi:clock-outline", "mapper": _identity_map},
            }
            for prop, config in text_props.items():
                if prop in data:
                    entities.append(AlpacaTelescopeTextSensor(coordinator, device, prop, config))
                    
            basic_props = {
                "aperturearea": {"name": "Aperture Area", "device_class": None, "unit": "m²", "icon": "mdi:circle-outline", "precision": None},
                "aperturediameter": {"name": "Aperture Diameter", "device_class": None, "unit": "m", "icon": "mdi:diameter-outline", "precision": 3},
                "focallength": {"name": "Focal Length", "device_class": None, "unit": "m", "icon": "mdi:arrow-expand-horizontal", "precision": 3},
                "sitelatitude": {"name": "Site Latitude", "device_class": None, "unit": "°", "icon": "mdi:latitude", "precision": 4},
                "sitelongitude": {"name": "Site Longitude", "device_class": None, "unit": "°", "icon": "mdi:longitude", "precision": 4},
                "siteelevation": {"name": "Site Elevation", "device_class": None, "unit": "m", "icon": "mdi:elevation-rise", "precision": 1},
                "slewsettletime": {"name": "Slew Settle Time", "device_class": None, "unit": "s", "icon": "mdi:timer-sand", "precision": None},
            }
            for prop, config in basic_props.items():
                if prop in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, prop, config))
                    
            if caps.get("cansetdeclinationrate") and "declinationrate" in data:
                entities.append(AlpacaObservingConditionSensor(coordinator, device, "declinationrate", 
                    {"name": "Declination Rate", "device_class": None, "unit": "arcsec/s", "icon": "mdi:delta", "precision": 5}))
            if caps.get("cansetrightascensionrate") and "rightascensionrate" in data:
                entities.append(AlpacaObservingConditionSensor(coordinator, device, "rightascensionrate", 
                    {"name": "RA Rate", "device_class": None, "unit": "s/s", "icon": "mdi:delta", "precision": 5}))
                    
            if caps.get("cansetguiderates"):
                if "guideratedeclination" in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, "guideratedeclination", 
                        {"name": "Guide Rate Dec", "device_class": None, "unit": "°/s", "icon": "mdi:speedometer", "precision": 5}))
                if "guideraterightascension" in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, "guideraterightascension", 
                        {"name": "Guide Rate RA", "device_class": None, "unit": "°/s", "icon": "mdi:speedometer", "precision": 5}))

        elif device["DeviceType"].lower() == "rotator":
            dev_key = f"rotator_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            
            rotator_props = {
                "position": {"name": "Position", "device_class": None, "unit": "°", "icon": "mdi:rotate-right", "precision": 2},
                "targetposition": {"name": "Target Position", "device_class": None, "unit": "°", "icon": "mdi:target", "precision": 2},
                "mechanicalposition": {"name": "Mechanical Position", "device_class": None, "unit": "°", "icon": "mdi:cog-rotate-right", "precision": 2},
                "stepsize": {"name": "Step Size", "device_class": None, "unit": "°", "icon": "mdi:ruler", "precision": 4},
            }
            for prop, config in rotator_props.items():
                if prop in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, prop, config))

        elif device["DeviceType"].lower() == "focuser":
            dev_key = f"focuser_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            
            focuser_props = {
                "position": {"name": "Position", "device_class": None, "unit": "Steps", "icon": "mdi:arrow-up-down", "precision": 0},
                "temperature": {"name": "Temperature", "device_class": SensorDeviceClass.TEMPERATURE, "unit": UnitOfTemperature.CELSIUS, "icon": "mdi:thermometer", "precision": 1},
                "stepsize": {"name": "Step Size", "device_class": None, "unit": "µm", "icon": "mdi:ruler", "precision": 4},
                "maxstep": {"name": "Max Step", "device_class": None, "unit": "Steps", "icon": "mdi:format-vertical-align-top", "precision": 0},
                "maxincrement": {"name": "Max Increment", "device_class": None, "unit": "Steps", "icon": "mdi:plus-box-outline", "precision": 0},
            }
            for prop, config in focuser_props.items():
                if prop in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, prop, config))
                    
        elif device["DeviceType"].lower() == "dome":
            dev_key = f"dome_{device['DeviceNumber']}"
            data = coordinator.data.get(dev_key, {})
            
            dome_props = {
                "altitude": {"name": "Altitude", "device_class": None, "unit": "°", "icon": "mdi:angle-acute", "precision": 1},
                "azimuth": {"name": "Azimuth", "device_class": None, "unit": "°", "icon": "mdi:compass", "precision": 1},
            }
            for prop, config in dome_props.items():
                if prop in data:
                    entities.append(AlpacaObservingConditionSensor(coordinator, device, prop, config))

    if entities:
        async_add_entities(entities)


class AlpacaObservingConditionSensor(AlpacaEntity, SensorEntity):
    """Observing Conditions Sensor."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_device_class = config["device_class"]
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_icon = config["icon"]
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if "precision" in config:
            self._attr_suggested_display_precision = config["precision"]

    @property
    def native_value(self):
        """Return the state of the sensor."""
        data = self.coordinator.data.get(self.dev_key, {})
        value = data.get(self.prop)
        if value is None:
            return None
        # Check if measurement is too old (ASCOM TimeSinceLastUpdate)
        age = data.get(f"age_{self.prop}")
        if age is not None and age > self.coordinator.max_sensor_age:
            LOGGER.debug(
                "Sensor %s age %.1fs exceeds max_sensor_age %ds, returning unavailable",
                self.prop, age, self.coordinator.max_sensor_age
            )
            return None
        return value

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})


class AlpacaSwitchValueSensor(AlpacaEntity, SensorEntity):
    """Switch Value Sensor for numeric switch metrics."""

    def __init__(self, coordinator, device, switch_id):
        """Initialize."""
        super().__init__(coordinator, device)
        self.switch_id = switch_id
        
        name = self.coordinator.data.get(self.dev_key, {}).get(f"name_{switch_id}", f"Switch {switch_id}")
        self._attr_name = f"{self._device_name} {name}"
        self._attr_unique_id = f"{super().unique_id}_{switch_id}_value"
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        data = self.coordinator.data.get(self.dev_key, {})
        return data.get(f"switchvalue_{self.switch_id}")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and f"switchvalue_{self.switch_id}" in self.coordinator.data.get(self.dev_key, {})


def _format_hms(value):
    """Format decimal hours as HHh MMm SSs."""
    negative = value < 0
    value = abs(value)
    h = int(value)
    m = int((value - h) * 60)
    s = (value - h - m / 60) * 3600
    sign = "-" if negative else ""
    return f"{sign}{h}h {m:02d}m {s:04.1f}s"


def _format_dms(value):
    """Format decimal degrees as DD° MM' SS\"."""
    negative = value < 0
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    s = (value - d - m / 60) * 3600
    sign = "-" if negative else ""
    return f"{sign}{d}° {m:02d}' {s:04.1f}\""


class AlpacaTelescopeCoordSensor(AlpacaEntity, SensorEntity):
    """Telescope coordinate sensor with astronomical formatting."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._format = config["format"]  # "hms" or "dms"
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]

    @property
    def native_value(self):
        """Return the formatted coordinate string."""
        data = self.coordinator.data.get(self.dev_key, {})
        value = data.get(self.prop)
        if value is None:
            return None
        if self._format == "hms":
            return _format_hms(value)
        return _format_dms(value)

    @property
    def extra_state_attributes(self):
        """Return raw decimal value as attribute for automations."""
        data = self.coordinator.data.get(self.dev_key, {})
        value = data.get(self.prop)
        if value is not None:
            return {"decimal": round(value, 6)}
        return {}

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})


class AlpacaTelescopeTextSensor(AlpacaEntity, SensorEntity):
    """Text-mapped sensor for properties like AlignmentMode, SideOfPier."""

    def __init__(self, coordinator, device, prop, config):
        """Initialize."""
        super().__init__(coordinator, device)
        self.prop = prop
        self._mapper = config["mapper"]
        self._attr_name = f"{self._device_name} {config['name']}"
        self._attr_unique_id = f"{super().unique_id}_{prop}"
        self._attr_icon = config["icon"]

    @property
    def native_value(self):
        """Return the mapped text value."""
        data = self.coordinator.data.get(self.dev_key, {})
        value = data.get(self.prop)
        if value is None:
            return None
        return self._mapper(value)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.prop in self.coordinator.data.get(self.dev_key, {})


class AlpacaFilterWheelSensor(AlpacaEntity, SensorEntity):
    """Sensor showing the current filter name from the filter wheel."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Filter"
        self._attr_unique_id = f"{super().unique_id}_filterwheel_name"
        self._attr_icon = "mdi:camera-iris"

    @property
    def native_value(self):
        """Return the name of the current filter."""
        data = self.coordinator.data.get(self.dev_key, {})
        position = data.get("position")
        names = data.get("names", [])
        if position is None:
            return None
        # position == -1 means the wheel is currently changing filters (ASCOM spec)
        if position < 0:
            return "Moving..."
        try:
            return names[int(position)]
        except IndexError:
            return str(position)

    @property
    def extra_state_attributes(self):
        """Expose the raw position index and full name list for automations."""
        data = self.coordinator.data.get(self.dev_key, {})
        attrs = {}
        position = data.get("position")
        names = data.get("names", [])
        if position is not None:
            attrs["position"] = position
        if names:
            attrs["filter_names"] = names
        return attrs

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and "position" in self.coordinator.data.get(self.dev_key, {})


class AlpacaFilterWheelOffsetSensor(AlpacaEntity, SensorEntity):
    """Sensor showing the focus offset of the currently selected filter."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_name = f"{self._device_name} Focus Offset"
        self._attr_unique_id = f"{super().unique_id}_filterwheel_offset"
        self._attr_icon = "mdi:bullseye-arrow"
        self._attr_native_unit_of_measurement = "steps"

    @property
    def native_value(self):
        """Return the focus offset for the current filter."""
        data = self.coordinator.data.get(self.dev_key, {})
        position = data.get("position")
        offsets = data.get("focusoffsets", [])
        if position is None or position < 0 or not offsets:
            return None
        try:
            return offsets[int(position)]
        except IndexError:
            return None

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        data = self.coordinator.data.get(self.dev_key, {})
        return super().available and "position" in data and bool(data.get("focusoffsets"))

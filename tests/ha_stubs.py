"""Minimal stand-ins for the Home Assistant and aiohttp modules the bridge imports.

The tests exercise the bridge logic (coordinator, entities) without a Home Assistant installation: only ``pytest``
(and Pillow for the camera test) is needed. Importing this module installs the stubs and puts ``custom_components``
on ``sys.path``. The stubs follow the behaviour of the real classes where the tests depend on it
(DataUpdateCoordinator.async_config_entry_first_refresh raises ConfigEntryNotReady when the update failed).
"""

from __future__ import annotations

import asyncio
import enum
import sys
import types
from pathlib import Path

CUSTOM_COMPONENTS = Path(__file__).resolve().parents[1] / "custom_components"


def _mod(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


# --- aiohttp -----------------------------------------------------------------------------------
class ClientError(Exception):
    pass


class ClientConnectorError(ClientError):
    pass


class ClientTimeout:
    def __init__(self, total=None):
        self.total = total


# --- homeassistant.exceptions / helpers.update_coordinator ---------------------------------------
class HomeAssistantError(Exception):
    pass


class ConfigEntryNotReady(HomeAssistantError):
    pass


class ServiceValidationError(HomeAssistantError):
    pass


class AbortFlow(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class UpdateFailed(Exception):
    pass


class ConfigFlow:
    """What the bridge uses of the config flow base class; results are plain dicts."""

    def __init_subclass__(cls, domain=None, **kwargs):
        cls.domain = domain

    hass = None
    unique_id = None
    configured_unique_ids: set = set()  # unique IDs of the entries that exist (set by the test)
    current_entries: list = []  # the entries that exist (set by the test)
    reconfigure_entry = None  # the entry that is reconfigured (set by the test)

    def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "errors": errors or {}, "data_schema": data_schema}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        if self.unique_id in self.configured_unique_ids:
            raise AbortFlow("already_configured")

    def _async_current_entries(self):
        return self.current_entries

    def _get_reconfigure_entry(self):
        return self.reconfigure_entry

    def async_update_reload_and_abort(self, entry, *, unique_id=None, title=None, data_updates=None):
        return {
            "type": "abort", "reason": "reconfigure_successful", "entry": entry,
            "unique_id": unique_id, "title": title, "data_updates": data_updates,
        }


class OptionsFlow:
    config_entry = None


class DataUpdateCoordinator:
    def __init__(self, hass, logger, *, name=None, update_interval=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True

    async def _async_update_data(self):
        raise NotImplementedError

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except UpdateFailed:
            self.last_update_success = False

    async def async_config_entry_first_refresh(self):
        await self.async_refresh()
        if not self.last_update_success:
            raise ConfigEntryNotReady


class CoordinatorEntity:
    def __init__(self, coordinator, context=None):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)

    @property
    def name(self):
        return getattr(self, "_attr_name", None)

    def async_write_ha_state(self):
        self.state_writes = getattr(self, "state_writes", 0) + 1

    def _handle_coordinator_update(self):
        self.async_write_ha_state()


class CoverEntityFeature(enum.IntFlag):
    OPEN = 1
    CLOSE = 2
    SET_POSITION = 4
    STOP = 8


class FakeTask:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def done(self):
        return self.cancelled


class FakeDeviceRegistry:
    """async_get(device_id) -> an object with `identifiers`."""

    def __init__(self):
        self.devices = {}

    def add(self, device_id, identifiers):
        self.devices[device_id] = types.SimpleNamespace(identifiers=set(identifiers))

    def async_get(self, device_id):
        return self.devices.get(device_id)


class FakeServices:
    def __init__(self):
        self.registered = {}

    def async_register(self, domain, name, handler, schema=None):
        self.registered[(domain, name)] = (handler, schema)

    def has_service(self, domain, name):
        return (domain, name) in self.registered

    def async_remove(self, domain, name):
        self.registered.pop((domain, name), None)


class FakeHass:
    """Home Assistant as far as the bridge uses it. `session` is what async_get_clientsession returns."""

    def __init__(self, session=None):
        self.session = session
        self.data = {}
        self.started_tasks = []
        self.services = FakeServices()
        self.device_registry = FakeDeviceRegistry()

    def async_create_task(self, coro, *args, **kwargs):
        # the smart poll that follows a command is not run in the tests
        coro.close()
        task = FakeTask()
        self.started_tasks.append(task)
        return task

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def install() -> None:
    if "homeassistant" in sys.modules:
        return

    _mod("aiohttp", ClientError=ClientError, ClientConnectorError=ClientConnectorError, ClientTimeout=ClientTimeout)
    # the old coordinator imported async_timeout (test_coordinator.py checks that the source no longer does)
    _mod("async_timeout", timeout=lambda seconds: asyncio.timeout(seconds))

    ha = _mod("homeassistant")
    _mod("homeassistant.core", HomeAssistant=object, ServiceCall=object, callback=lambda func: func)
    _mod("homeassistant.config_entries", ConfigEntry=object, ConfigFlow=ConfigFlow, OptionsFlow=OptionsFlow)
    _mod(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
        ConfigEntryNotReady=ConfigEntryNotReady,
        ServiceValidationError=ServiceValidationError,
    )
    _mod(
        "homeassistant.const",
        PERCENTAGE="%",
        UnitOfPressure=types.SimpleNamespace(HPA="hPa"),
        UnitOfTemperature=types.SimpleNamespace(CELSIUS="°C"),
        UnitOfSpeed=types.SimpleNamespace(METERS_PER_SECOND="m/s"),
    )

    helpers = _mod("homeassistant.helpers")
    helpers.update_coordinator = _mod(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=DataUpdateCoordinator,
        UpdateFailed=UpdateFailed,
        CoordinatorEntity=CoordinatorEntity,
    )
    helpers.aiohttp_client = _mod(
        "homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: hass.session
    )
    helpers.config_validation = _mod(
        "homeassistant.helpers.config_validation", string=str, multi_select=lambda mapping: (lambda value: value)
    )
    helpers.device_registry = _mod(
        "homeassistant.helpers.device_registry", async_get=lambda hass: hass.device_registry
    )
    helpers.entity = _mod("homeassistant.helpers.entity", DeviceInfo=dict)
    ha.helpers = helpers

    components = _mod("homeassistant.components")
    components.cover = _mod(
        "homeassistant.components.cover",
        CoverEntity=type("CoverEntity", (), {}),
        CoverDeviceClass=types.SimpleNamespace(AWNING="awning"),
        CoverEntityFeature=CoverEntityFeature,
    )
    components.camera = _mod("homeassistant.components.camera", Camera=type("Camera", (), {"__init__": lambda self: None}))
    components.number = _mod(
        "homeassistant.components.number",
        NumberEntity=type("NumberEntity", (), {}),
        NumberMode=types.SimpleNamespace(BOX="box", SLIDER="slider"),
    )
    components.button = _mod("homeassistant.components.button", ButtonEntity=type("ButtonEntity", (), {}))
    components.switch = _mod("homeassistant.components.switch", SwitchEntity=type("SwitchEntity", (), {}))
    components.binary_sensor = _mod(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=type("BinarySensorEntity", (), {}),
        BinarySensorDeviceClass=types.SimpleNamespace(SAFETY="safety", MOVING="moving"),
    )
    components.select = _mod("homeassistant.components.select", SelectEntity=type("SelectEntity", (), {}))
    components.sensor = _mod(
        "homeassistant.components.sensor",
        SensorEntity=type("SensorEntity", (), {}),
        SensorDeviceClass=types.SimpleNamespace(
            TEMPERATURE="temperature", HUMIDITY="humidity", PRESSURE="pressure", WIND_SPEED="wind_speed", POWER_FACTOR="power_factor"
        ),
        SensorStateClass=types.SimpleNamespace(MEASUREMENT="measurement"),
    )
    ha.components = components

    sys.path.insert(0, str(CUSTOM_COMPONENTS))


install()

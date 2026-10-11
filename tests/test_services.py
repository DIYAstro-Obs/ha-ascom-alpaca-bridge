"""Services (review stage 2: B5, B12): which device they act on, capability checks, mount state, unload."""
import asyncio
import importlib
import types

import pytest

from ha_stubs import HomeAssistantError, ServiceValidationError
from helpers import FakeAlpaca, device, make_coordinator, run

bridge = importlib.import_module("ascom_alpaca_bridge")
const = importlib.import_module("ascom_alpaca_bridge.const")
DOMAIN = const.DOMAIN


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """The 1 s pause after switching tracking off is not waited for."""

    async def instant(_seconds, *args, **kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _setup(devices, data):
    alpaca = FakeAlpaca()
    coordinator = make_coordinator(alpaca, devices)
    coordinator.data = data
    hass = coordinator.hass
    hass.data[DOMAIN] = {"entry": coordinator}
    bridge._register_services(hass)
    return alpaca, hass, coordinator


def _call(hass, name, **data):
    handler, schema = hass.services.registered[(DOMAIN, name)]
    return run(handler(types.SimpleNamespace(data=schema(data))))


def test_a_service_goes_to_the_only_device_of_its_type():
    alpaca, hass, _ = _setup([device("Camera")], {"camera_0": {}})

    _call(hass, "camera_start_exposure", duration=30)

    put = alpaca.last_put("startexposure")
    assert put["Duration"] == "30.0" and put["Light"] == "True"


def test_a_dark_frame_can_be_requested():
    alpaca, hass, _ = _setup([device("Camera")], {"camera_0": {}})

    _call(hass, "camera_start_exposure", duration=30, light=False)

    assert alpaca.last_put("startexposure")["Light"] == "False"


def test_several_devices_of_a_type_need_a_device_id():
    devices = [device("Camera", 0), device("Camera", 1)]
    alpaca, hass, coordinator = _setup(devices, {"camera_0": {}, "camera_1": {}})

    with pytest.raises(ServiceValidationError, match="device_id"):
        _call(hass, "camera_start_exposure", duration=5)
    assert alpaca.puts == []

    hass.device_registry.add("second", [(DOMAIN, coordinator.device_uid(devices[1]))])
    _call(hass, "camera_start_exposure", duration=5, device_id="second")

    assert [(p[0], p[1]) for p in alpaca.puts] == [("camera", 1)]


def test_an_unknown_device_id_is_refused():
    _, hass, _ = _setup([device("Camera")], {"camera_0": {}})

    with pytest.raises(ServiceValidationError, match="Unknown device"):
        _call(hass, "camera_start_exposure", duration=5, device_id="nope")


def test_a_service_for_a_type_that_is_not_configured_is_refused():
    _, hass, _ = _setup([device("Camera")], {"camera_0": {}})

    with pytest.raises(ServiceValidationError, match="No dome"):
        _call(hass, "dome_slew_az", azimuth=10)


def test_a_function_the_device_does_not_report_is_refused():
    alpaca, hass, _ = _setup([device("Dome")], {"dome_0": {"capabilities": {"cansetazimuth": False}}})

    with pytest.raises(ServiceValidationError, match="cansetazimuth"):
        _call(hass, "dome_slew_az", azimuth=10)
    assert alpaca.puts == []


def test_a_function_the_device_reports_is_sent():
    alpaca, hass, _ = _setup([device("Dome")], {"dome_0": {"capabilities": {"cansetazimuth": True}}})

    _call(hass, "dome_slew_az", azimuth=95.5)

    assert alpaca.last_put("slewtoazimuth")["Azimuth"] == "95.5"


def test_a_parked_mount_does_not_slew():
    data = {"telescope_0": {"atpark": True, "tracking": False, "capabilities": {"canslewasync": True, "cansettracking": True}}}
    alpaca, hass, _ = _setup([device("Telescope")], data)

    with pytest.raises(HomeAssistantError, match="parked"):
        _call(hass, "slew_to_coordinates", ra=5.5, dec=10)
    assert alpaca.puts == []


def test_an_equatorial_slew_switches_tracking_on_first():
    data = {"telescope_0": {"atpark": False, "tracking": False, "capabilities": {"canslewasync": True, "cansettracking": True}}}
    alpaca, hass, _ = _setup([device("Telescope")], data)

    _call(hass, "slew_to_coordinates", ra=5.5, dec=10)

    assert [p[2] for p in alpaca.puts] == ["tracking", "slewtocoordinatesasync"]
    assert alpaca.puts[0][3]["Tracking"] == "True"
    assert alpaca.puts[1][3]["RightAscension"] == "5.5"


def test_an_alt_az_slew_switches_tracking_off_first():
    data = {"telescope_0": {"atpark": False, "tracking": True, "capabilities": {"canslewaltazasync": True, "cansettracking": True}}}
    alpaca, hass, _ = _setup([device("Telescope")], data)

    _call(hass, "slew_to_alt_az", alt=45, az=180)

    assert [p[2] for p in alpaca.puts] == ["tracking", "slewtoaltazasync"]
    assert alpaca.puts[0][3]["Tracking"] == "False"


def test_the_subframe_is_sent_as_four_properties():
    alpaca, hass, _ = _setup([device("Camera")], {"camera_0": {}})

    _call(hass, "camera_set_roi", start_x=10, start_y=20, num_x=300, num_y=200)

    assert [(p[2], list(p[3].values())[-1]) for p in alpaca.puts] == [
        ("numx", "300"), ("numy", "200"), ("startx", "10"), ("starty", "20"),
    ]


def test_unloading_the_last_entry_removes_every_service():
    _, hass, coordinator = _setup([device("Camera")], {"camera_0": {}})

    async def unload_platforms(entry, platforms):
        return True

    hass.config_entries = types.SimpleNamespace(async_unload_platforms=unload_platforms)
    assert len(hass.services.registered) == len(bridge.SERVICE_NAMES) == 12

    run(bridge.async_unload_entry(hass, types.SimpleNamespace(entry_id="entry")))

    assert hass.services.registered == {}

"""Entity details of review stage 2: B7, B9 to B11 and the small items of group C."""
import importlib
import types

import pytest

from ha_stubs import CoverEntityFeature
from helpers import FakeAlpaca, device, make_coordinator, run

sensor_mod = importlib.import_module("ascom_alpaca_bridge.sensor")
number_mod = importlib.import_module("ascom_alpaca_bridge.number")
button_mod = importlib.import_module("ascom_alpaca_bridge.button")
switch_mod = importlib.import_module("ascom_alpaca_bridge.switch")
select_mod = importlib.import_module("ascom_alpaca_bridge.select")
cover_mod = importlib.import_module("ascom_alpaca_bridge.cover")


def _entities(module, coordinator):
    added = []
    coordinator.hass.data["ascom_alpaca_bridge"] = {"e": coordinator}
    run(module.async_setup_entry(coordinator.hass, types.SimpleNamespace(entry_id="e"), lambda items: added.extend(items)))
    return added


def _coordinator(dev, data):
    coordinator = make_coordinator(FakeAlpaca(), [dev])
    coordinator.data = {f"{dev['DeviceType'].lower()}_{dev['DeviceNumber']}": data}
    return coordinator


# --- B7: camera sensors only for what the camera reports -----------------------------------------
def test_camera_sensors_exist_only_for_the_properties_the_camera_has():
    coordinator = _coordinator(device("Camera"), {"camerastate": 0, "ccdtemperature": -10.0, "capabilities": {}})

    props = {getattr(e, "prop", None) for e in _entities(sensor_mod, coordinator)}

    assert "ccdtemperature" in props and "camerastate" in props
    assert "heatsinktemperature" not in props and "fullwellcapacity" not in props


# --- B9: seconds never show as 60.0 ----------------------------------------------------------------
@pytest.mark.parametrize(
    "hours, text",
    [(0.0, "0h 00m 00.0s"), (5.5, "5h 30m 00.0s"), (5.99999999, "6h 00m 00.0s"), (23.9999999, "24h 00m 00.0s"), (-1.25, "-1h 15m 00.0s")],
)
def test_hours_format(hours, text):
    assert sensor_mod._format_hms(hours) == text


@pytest.mark.parametrize(
    "degrees, text",
    [(0.0, "0° 00' 00.0\""), (12.5, "12° 30' 00.0\""), (89.99999999, "90° 00' 00.0\""), (-0.5, "-0° 30' 00.0\""), (-0.0000001, "0° 00' 00.0\"")],
)
def test_degrees_format(degrees, text):
    assert sensor_mod._format_dms(degrees) == text


# --- B10: a focuser that did not report its maximum --------------------------------------------------
def test_a_focuser_without_a_reported_maximum_gets_a_default():
    dev = device("Focuser")
    coordinator = _coordinator(dev, {"position": 100, "capabilities": {"absolute": True, "maxstep": None}})

    assert number_mod.AlpacaFocuserTargetNumber(coordinator, dev).native_max_value == 100000.0


# --- B11: subframe limit, apply order, light / dark -----------------------------------------------------
def test_the_subframe_is_limited_by_the_sensor_size():
    coordinator = _coordinator(
        device("Camera"),
        {"numx": 10, "numy": 10, "startx": 0, "starty": 0, "capabilities": {"cameraxsize": 6248, "cameraysize": 4176}},
    )

    numbers = {e.prop: e for e in _entities(number_mod, coordinator) if hasattr(e, "prop")}

    assert numbers["numx"].native_max_value == 6248
    assert numbers["starty"].native_max_value == 4176


def test_apply_camera_settings_sets_binning_first_and_the_subframe_last():
    alpaca = FakeAlpaca()
    dev = device("Camera")
    coordinator = make_coordinator(alpaca, [dev])
    coordinator.data = {"camera_0": {}}
    group = coordinator.target_group("camera_0", "camera")
    group.update({"numx": 100, "startx": 5, "gain": 120, "binx": 2, "readoutmode": 1})

    run(button_mod.AlpacaCameraApplySettingsButton(coordinator, dev).async_press())

    assert [p[2] for p in alpaca.puts] == ["binx", "readoutmode", "gain", "numx", "startx"]
    assert group == {}  # applied


def test_the_start_button_uses_the_light_switch():
    alpaca = FakeAlpaca()
    dev = device("Camera")
    coordinator = make_coordinator(alpaca, [dev])
    coordinator.data = {"camera_0": {}}
    light = switch_mod.AlpacaCameraLightSwitch(coordinator, dev)
    start = button_mod.AlpacaCameraStartExposureButton(coordinator, dev)

    assert light.is_on is True
    run(start.async_press())
    assert alpaca.last_put("startexposure")["Light"] == "True"

    run(light.async_turn_off())
    run(start.async_press())
    assert alpaca.last_put("startexposure")["Light"] == "False"
    assert light.is_on is False


# --- B12: the slew button prepares the mount -------------------------------------------------------------
def test_the_slew_button_refuses_a_parked_mount():
    alpaca = FakeAlpaca()
    dev = device("Telescope")
    coordinator = make_coordinator(alpaca, [dev])
    coordinator.data = {"telescope_0": {"atpark": True, "tracking": False, "capabilities": {"canslewasync": True}}}
    coordinator.set_target("telescope_0", "target_ra", 5.0)
    coordinator.set_target("telescope_0", "target_dec", 10.0)
    button = button_mod.AlpacaTelescopeSlewButton(
        coordinator, dev, "slewtocoordinatesasync", {"name": "Slew", "icon": "x"},
        target_keys=("target_ra", "target_dec"), param_names=("RightAscension", "Declination"),
    )

    with pytest.raises(Exception, match="parked"):
        run(button.async_press())
    assert alpaca.puts == []


# --- group C -----------------------------------------------------------------------------------------------
def test_the_tracking_rate_of_a_mount_that_cannot_change_it_is_a_sensor():
    coordinator = _coordinator(device("Telescope"), {"trackingrate": 0, "capabilities": {"cansettracking": False}})

    sensors = [e for e in _entities(sensor_mod, coordinator) if getattr(e, "prop", None) == "trackingrate"]

    assert len(sensors) == 1 and sensors[0].native_value == "Sidereal"


def test_no_tracking_rate_sensor_when_the_select_exists():
    coordinator = _coordinator(device("Telescope"), {"trackingrate": 0, "capabilities": {"cansettracking": True}})

    assert not [e for e in _entities(sensor_mod, coordinator) if getattr(e, "prop", None) == "trackingrate"]


def test_fixed_values_are_not_statistics_and_measurements_are():
    dev = device("Telescope")
    coordinator = _coordinator(dev, {"focallength": 1.2, "rightascensionrate": 0.0, "capabilities": {"cansetrightascensionrate": True}})

    sensors = {e.prop: e for e in _entities(sensor_mod, coordinator) if hasattr(e, "prop")}

    assert sensors["focallength"]._attr_state_class is None
    assert sensors["rightascensionrate"]._attr_state_class == "measurement"


def test_filters_with_the_same_name_can_all_be_selected():
    dev = device("FilterWheel")
    coordinator = _coordinator(dev, {"position": 0, "names": ["L", "Empty", "Empty", "Ha"]})
    select = select_mod.AlpacaFilterWheelSelect(coordinator, dev)

    assert select.options == ["L", "Empty", "Empty (2)", "Ha"]
    run(select.async_select_option("Empty (2)"))
    assert coordinator.get_target("filterwheel_0", "target_position") == 2
    assert select.current_option == "Empty (2)"


def test_a_cover_calibrator_with_a_cover_offers_stop():
    dev = device("CoverCalibrator")
    cover = cover_mod.AlpacaCover(_coordinator(dev, {"coverstate": 1}), dev)

    assert cover.supported_features == CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP

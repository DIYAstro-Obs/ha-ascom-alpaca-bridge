"""A6 / A7: option changes apply at once, and the units of the telescope rates are the ASCOM ones."""
import importlib
import types

from helpers import FakeAlpaca, device, make_coordinator, run

bridge = importlib.import_module("ascom_alpaca_bridge")
sensor_mod = importlib.import_module("ascom_alpaca_bridge.sensor")
number_mod = importlib.import_module("ascom_alpaca_bridge.number")


def test_the_options_listener_applies_interval_and_max_sensor_age():
    coordinator = make_coordinator(FakeAlpaca(), [device("ObservingConditions")], scan_interval=10, max_sensor_age=600)
    coordinator.hass.data["ascom_alpaca_bridge"] = {"entry-1": coordinator}
    entry = types.SimpleNamespace(entry_id="entry-1", options={"scan_interval": 30, "max_sensor_age": 90})

    run(bridge._async_update_listener(coordinator.hass, entry))

    assert coordinator.update_interval.total_seconds() == 30
    assert coordinator.max_sensor_age == 90


def _telescope_coordinator():
    dev = device("Telescope")
    coordinator = make_coordinator(FakeAlpaca(), [dev])
    coordinator.data = {
        "telescope_0": {
            "declinationrate": 0.0,
            "rightascensionrate": 0.0,
            "capabilities": {"cansetdeclinationrate": True, "cansetrightascensionrate": True},
        }
    }
    coordinator.hass.data["ascom_alpaca_bridge"] = {"e": coordinator}
    return coordinator


def _setup(module, coordinator):
    added = []
    entry = types.SimpleNamespace(entry_id="e")
    run(module.async_setup_entry(coordinator.hass, entry, lambda entities: added.extend(entities)))
    return added


def test_declination_rate_is_in_arcseconds_per_second():
    coordinator = _telescope_coordinator()

    sensors = _setup(sensor_mod, coordinator)
    numbers = _setup(number_mod, coordinator)

    sensor = next(s for s in sensors if getattr(s, "prop", None) == "declinationrate")
    number = next(n for n in numbers if getattr(n, "prop", None) == "declinationrate")
    assert sensor._attr_native_unit_of_measurement == "arcsec/s"
    assert number._attr_native_unit_of_measurement == "arcsec/s"

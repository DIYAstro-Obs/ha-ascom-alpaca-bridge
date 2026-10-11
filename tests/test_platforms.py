"""Every platform module imports and can set up its entities for a bridge with one device of each type."""
import importlib
import types

import pytest

from helpers import FakeAlpaca, device, make_coordinator, run

const = importlib.import_module("ascom_alpaca_bridge.const")

DEVICE_TYPES = [
    "ObservingConditions", "SafetyMonitor", "Switch", "Dome", "CoverCalibrator",
    "Telescope", "Rotator", "FilterWheel", "Focuser", "Camera",
]


def _alpaca():
    alpaca = FakeAlpaca()
    alpaca.set("safetymonitor", 0, "issafe", True)
    alpaca.set("observingconditions", 0, "temperature", 12.5)
    alpaca.set("switch", 0, "maxswitch", 2)
    alpaca.set("switch", 0, "getswitch", True, "0")
    alpaca.set("switch", 0, "canwrite", True, "0")
    alpaca.set("switch", 0, "getswitchvalue", 1.0, "1")
    alpaca.set("switch", 0, "canwrite", True, "1")
    alpaca.set("switch", 0, "maxswitchvalue", 100.0, "1")
    alpaca.set("dome", 0, "shutterstatus", 1)
    alpaca.set("dome", 0, "cansetshutter", True)
    alpaca.set("covercalibrator", 0, "coverstate", 1)
    alpaca.set("covercalibrator", 0, "calibratorstate", 1)
    alpaca.set("telescope", 0, "rightascension", 5.5)
    alpaca.set("telescope", 0, "canslewasync", True)
    alpaca.set("telescope", 0, "canpark", True)
    alpaca.set("rotator", 0, "position", 10.0)
    alpaca.set("filterwheel", 0, "position", 1)
    alpaca.set("filterwheel", 0, "names", ["L", "R", "G", "B"])
    alpaca.set("focuser", 0, "position", 1000)
    alpaca.set("camera", 0, "camerastate", 0)
    alpaca.set("camera", 0, "ccdtemperature", -10.0)
    alpaca.set("camera", 0, "readoutmodes", ["Normal"])
    return alpaca


@pytest.mark.parametrize("platform", const.PLATFORMS)
def test_a_platform_sets_up_its_entities(platform):
    alpaca = _alpaca()
    coordinator = make_coordinator(alpaca, [device(t) for t in DEVICE_TYPES])
    run(coordinator.async_refresh())
    assert coordinator.last_update_success
    coordinator.hass.data["ascom_alpaca_bridge"] = {"e": coordinator}
    module = importlib.import_module(f"ascom_alpaca_bridge.{platform}")

    added = []
    run(module.async_setup_entry(coordinator.hass, types.SimpleNamespace(entry_id="e"), lambda entities: added.extend(entities)))

    assert added, f"{platform} created no entity"
    # every entity answers its state properties without raising
    for entity in added:
        for prop in ("native_value", "is_on", "is_closed", "current_option", "available", "supported_features"):
            getattr(entity, prop, None)

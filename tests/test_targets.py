"""A2: a value the user entered (target position, exposure, ...) has to survive the next poll until it is applied."""
import importlib

import pytest

from helpers import FakeAlpaca, device, make_coordinator, run

number_mod = importlib.import_module("ascom_alpaca_bridge.number")
button_mod = importlib.import_module("ascom_alpaca_bridge.button")


def _refreshed(alpaca, dev):
    coordinator = make_coordinator(alpaca, [dev])
    run(coordinator.async_refresh())
    return coordinator


def test_rotator_target_survives_a_poll_and_is_sent_by_the_button():
    dev = device("Rotator")
    alpaca = FakeAlpaca()
    alpaca.set("rotator", 0, "position", 10.0)
    alpaca.set("rotator", 0, "stepsize", 0.1)
    coordinator = _refreshed(alpaca, dev)

    number = number_mod.AlpacaRotatorTargetNumber(coordinator, dev)
    run(number.async_set_native_value(123.0))
    run(coordinator.async_refresh())

    assert number.native_value == 123.0
    run(button_mod.AlpacaRotatorMoveAbsoluteAction(coordinator, dev).async_press())
    assert alpaca.last_put("moveabsolute")["Position"] == "123.0"


def test_rotator_relative_move_and_sync_values_survive_a_poll():
    dev = device("Rotator")
    alpaca = FakeAlpaca()
    alpaca.set("rotator", 0, "position", 10.0)
    coordinator = _refreshed(alpaca, dev)

    move = number_mod.AlpacaRotatorVirtualNumber(coordinator, dev, "move_relative", {"name": "m", "min": -360, "max": 360, "icon": "x"})
    sync = number_mod.AlpacaRotatorVirtualNumber(coordinator, dev, "sync_position", {"name": "s", "min": 0, "max": 360, "icon": "x"})
    run(move.async_set_native_value(15.0))
    run(sync.async_set_native_value(200.0))
    run(coordinator.async_refresh())

    assert move.native_value == 15.0
    assert sync.native_value == 200.0
    run(button_mod.AlpacaRotatorMoveButton(coordinator, dev).async_press())
    assert alpaca.last_put("move")["Position"] == "15.0"


def test_focuser_target_survives_a_poll():
    dev = device("Focuser")
    alpaca = FakeAlpaca()
    alpaca.set("focuser", 0, "position", 5000)
    alpaca.set("focuser", 0, "absolute", True)
    alpaca.set("focuser", 0, "maxstep", 50000)
    coordinator = _refreshed(alpaca, dev)

    number = number_mod.AlpacaFocuserTargetNumber(coordinator, dev)
    run(number.async_set_native_value(20000))
    run(coordinator.async_refresh())

    assert number.native_value == 20000
    run(button_mod.AlpacaFocuserMoveAction(coordinator, dev).async_press())
    assert alpaca.last_put("move")["Position"] == "20000"


def test_dome_target_survives_a_poll():
    dev = device("Dome")
    alpaca = FakeAlpaca()
    alpaca.set("dome", 0, "azimuth", 10.0)
    alpaca.set("dome", 0, "altitude", 5.0)
    coordinator = _refreshed(alpaca, dev)

    number = number_mod.AlpacaDomeTargetNumber(coordinator, dev, "azimuth", {"name": "Target Azimuth", "min": 0.0, "max": 360.0, "icon": "x"})
    run(number.async_set_native_value(180.0))
    run(coordinator.async_refresh())

    assert number.native_value == 180.0
    run(button_mod.AlpacaDomeSlewAction(coordinator, dev, "azimuth", "Slew Target Azimuth", "x").async_press())
    assert alpaca.last_put("slewtoazimuth")["Azimuth"] == "180.0"


def test_camera_exposure_survives_a_poll_and_is_not_cleared_by_starting():
    dev = device("Camera")
    alpaca = FakeAlpaca()
    coordinator = _refreshed(alpaca, dev)

    number = number_mod.AlpacaCameraExposureNumber(coordinator, dev)
    run(number.async_set_native_value(120.0))
    run(coordinator.async_refresh())
    assert number.native_value == 120.0

    run(button_mod.AlpacaCameraStartExposureButton(coordinator, dev).async_press())
    assert alpaca.last_put("startexposure")["Duration"] == "120.0"
    assert number.native_value == 120.0  # the next frame uses the same duration


def test_a_target_is_cleared_once_it_is_applied():
    dev = device("Rotator")
    alpaca = FakeAlpaca()
    alpaca.set("rotator", 0, "position", 10.0)
    coordinator = _refreshed(alpaca, dev)
    number = number_mod.AlpacaRotatorTargetNumber(coordinator, dev)
    run(number.async_set_native_value(123.0))

    run(button_mod.AlpacaRotatorMoveAbsoluteAction(coordinator, dev).async_press())
    alpaca.set("rotator", 0, "position", 123.0)
    run(coordinator.async_refresh())

    assert number.native_value == pytest.approx(123.0)  # the live position, no stale target
    assert coordinator.get_target("rotator_0", "rotator_target_position") is None

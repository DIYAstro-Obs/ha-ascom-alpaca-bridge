"""A4 / A5: state mapping of the cover entity (roof / flat panel cover) and what it offers."""
import importlib

import pytest

from ha_stubs import CoverEntityFeature, HomeAssistantError
from helpers import FakeAlpaca, device, make_coordinator, run

cover_mod = importlib.import_module("ascom_alpaca_bridge.cover")


def _cover(devtype, data):
    dev = device(devtype)
    coordinator = make_coordinator(FakeAlpaca(), [dev])
    coordinator.data = {f"{devtype.lower()}_0": data}
    return cover_mod.AlpacaCover(coordinator, dev)


# ASCOM ShutterState: 0 open, 1 closed, 2 opening, 3 closing, 4 error
@pytest.mark.parametrize(
    "status, closed, opening, closing",
    [
        (0, False, False, False),
        (1, True, False, False),
        (2, False, True, False),
        (3, False, False, True),
        (4, None, False, False),  # error: neither open nor closed
        (None, None, False, False),
    ],
)
def test_dome_shutter_status(status, closed, opening, closing):
    data = {} if status is None else {"shutterstatus": status}
    cover = _cover("Dome", data)
    assert cover.is_closed is closed
    assert bool(cover.is_opening) is opening
    assert bool(cover.is_closing) is closing


# ASCOM CoverStatus: 0 not present, 1 closed, 2 moving, 3 open, 4 unknown, 5 error
@pytest.mark.parametrize(
    "status, closed",
    [(0, None), (1, True), (3, False), (4, None), (5, None)],
)
def test_cover_calibrator_cover_state(status, closed):
    cover = _cover("CoverCalibrator", {"coverstate": status})
    assert cover.is_closed is closed
    assert not cover.is_opening and not cover.is_closing


def test_cover_calibrator_moving_goes_away_from_the_last_settled_position():
    dev = device("CoverCalibrator")
    coordinator = make_coordinator(FakeAlpaca(), [dev])
    data = coordinator.data = {"covercalibrator_0": {"coverstate": 1}}
    cover = cover_mod.AlpacaCover(coordinator, dev)

    data["covercalibrator_0"]["coverstate"] = 2  # it was closed, now it moves
    cover._handle_coordinator_update()
    assert cover.is_opening and not cover.is_closing and cover.is_closed is None

    data["covercalibrator_0"]["coverstate"] = 3  # open
    cover._handle_coordinator_update()
    data["covercalibrator_0"]["coverstate"] = 2  # and moves again
    cover._handle_coordinator_update()
    assert cover.is_closing and not cover.is_opening


def test_cover_calibrator_moving_after_a_restart_is_unknown():
    cover = _cover("CoverCalibrator", {"coverstate": 2})
    assert not cover.is_opening and not cover.is_closing
    assert cover.is_closed is None


def test_a_dome_without_shutter_control_offers_only_stop():
    cover = _cover("Dome", {"shutterstatus": 0, "capabilities": {"cansetshutter": False}})
    assert cover.supported_features == CoverEntityFeature.STOP


def test_a_dome_with_shutter_control_offers_open_close_stop():
    cover = _cover("Dome", {"shutterstatus": 0, "capabilities": {"cansetshutter": True}})
    assert cover.supported_features == CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP


def test_a_failed_close_is_reported_to_the_caller():
    alpaca = FakeAlpaca()
    alpaca.put_errors["closeshutter"] = (1035, "Shutter motor stalled")
    dev = device("Dome")
    coordinator = make_coordinator(alpaca, [dev])
    coordinator.data = {"dome_0": {"shutterstatus": 0, "capabilities": {"cansetshutter": True}}}
    cover = cover_mod.AlpacaCover(coordinator, dev)

    with pytest.raises(HomeAssistantError, match="stalled"):
        run(cover.async_close_cover())

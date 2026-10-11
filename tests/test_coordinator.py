"""Load, log noise, follow-up polls and device identity of the coordinator (review stage 2: B2, B4, B6)."""
import importlib
import logging

import pytest

from helpers import FakeAlpaca, device, make_coordinator, run

const = importlib.import_module("ascom_alpaca_bridge.const")
cover_mod = importlib.import_module("ascom_alpaca_bridge.cover")


def test_the_requests_of_one_poll_do_not_all_run_at_once():
    alpaca = FakeAlpaca()
    devices = [device("ObservingConditions"), device("Telescope"), device("Camera")]
    coordinator = make_coordinator(alpaca, devices)

    run(coordinator.async_refresh())

    assert len(alpaca.requests) > 60  # a poll of these three devices is a lot of requests
    assert 1 < alpaca.max_inflight <= const.MAX_CONCURRENT_REQUESTS


def test_the_polling_interval_is_not_faster_than_the_minimum():
    coordinator = make_coordinator(FakeAlpaca(), [device("Dome")], scan_interval=1)
    assert coordinator.update_interval.total_seconds() == const.MIN_SCAN_INTERVAL

    coordinator.set_scan_interval(2)
    assert coordinator.update_interval.total_seconds() == const.MIN_SCAN_INTERVAL
    coordinator.set_scan_interval(30)
    assert coordinator.update_interval.total_seconds() == 30


def _warnings(caplog, text):
    return [r for r in caplog.records if r.levelno == logging.WARNING and text in r.getMessage()]


def test_a_property_that_answers_http_404_is_reported_once(caplog):
    alpaca = FakeAlpaca()
    alpaca.set_status("safetymonitor", 0, "issafe", 404)
    coordinator = make_coordinator(alpaca, [device("SafetyMonitor")])

    with caplog.at_level(logging.WARNING, logger="ascom_alpaca_bridge"):
        for _ in range(3):
            run(coordinator.async_refresh())
        assert len(_warnings(caplog, "HTTP 404")) == 1

        # it answers again, and later it is gone again: that is worth a new warning
        alpaca.set_status("safetymonitor", 0, "issafe", None)
        alpaca.set("safetymonitor", 0, "issafe", True)
        run(coordinator.async_refresh())
        alpaca.set_status("safetymonitor", 0, "issafe", 404)
        run(coordinator.async_refresh())
        assert len(_warnings(caplog, "HTTP 404")) == 2


def test_a_new_command_replaces_the_follow_up_poll_and_unload_stops_it():
    coordinator = make_coordinator(FakeAlpaca(), [device("Dome")])

    run(coordinator.send_command("dome", 0, "openshutter"))
    run(coordinator.send_command("dome", 0, "closeshutter"))
    first, second = coordinator.hass.started_tasks
    assert first.cancelled and not second.cancelled

    coordinator.cancel_smart_poll()
    assert second.cancelled


def test_the_unique_id_is_the_alpaca_unique_id_when_it_is_usable():
    camera = dict(device("Camera"), UniqueId="GUID-CAMERA")
    dome = dict(device("Dome"), UniqueId="GUID-DOME")
    coordinator = make_coordinator(FakeAlpaca(), [camera, dome])

    assert coordinator.device_uid(camera) == "GUID-CAMERA"
    assert coordinator.device_uid(dome) == "GUID-DOME"


@pytest.mark.parametrize("unique_id", [None, "", "null", "None", "string"])
def test_a_missing_or_generic_unique_id_falls_back_to_the_server_and_device(unique_id):
    dome = dict(device("Dome", 2), UniqueId=unique_id)
    coordinator = make_coordinator(FakeAlpaca(), [dome], uid_host="192.168.1.9")

    assert coordinator.device_uid(dome) == "192.168.1.9_dome_2"


def test_devices_that_share_a_unique_id_get_different_entity_ids():
    dome = dict(device("Dome"), UniqueId="SAME")
    calibrator = dict(device("CoverCalibrator"), UniqueId="SAME")
    coordinator = make_coordinator(FakeAlpaca(), [dome, calibrator])
    coordinator.data = {}

    assert coordinator.device_uid(dome) != coordinator.device_uid(calibrator)
    first = cover_mod.AlpacaCover(coordinator, dome)
    second = cover_mod.AlpacaCover(coordinator, calibrator)
    assert first.unique_id != second.unique_id

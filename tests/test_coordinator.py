"""Load, log noise, follow-up polls and device identity of the coordinator (review stage 2: B2, B4, B6)."""
import importlib
import logging
import time

import pytest

from ha_stubs import UpdateFailed
from helpers import FakeAlpaca, device, make_coordinator, run

const = importlib.import_module("ascom_alpaca_bridge.const")
cover_mod = importlib.import_module("ascom_alpaca_bridge.cover")


def test_a_device_gets_a_limited_number_of_requests_at_the_same_time():
    alpaca = FakeAlpaca()
    devices = [device("ObservingConditions"), device("Telescope"), device("Camera")]
    coordinator = make_coordinator(alpaca, devices)

    run(coordinator.async_refresh())

    assert len(alpaca.requests) > 60  # a poll of these three devices is a lot of requests
    for dev_type in ("observingconditions", "telescope", "camera"):
        assert 1 < alpaca.max_inflight_by_device[dev_type] <= const.MAX_CONCURRENT_REQUESTS


def test_a_slow_device_does_not_delay_the_others():
    """A hanging driver used to take the places of the others (one limit for all): now only its own."""
    alpaca = FakeAlpaca()
    alpaca.delay = {"telescope": 0.1}  # 31 requests, 4 at a time: about 0.8 s
    devices = [device("Telescope"), device("Dome"), device("ObservingConditions"), device("SafetyMonitor")]
    coordinator = make_coordinator(alpaca, devices)
    started = time.monotonic()

    run(coordinator.async_refresh())

    finished = {dev: alpaca.last_finished[dev] - started for dev in ("telescope", "dome", "observingconditions", "safetymonitor")}
    assert finished["telescope"] > 0.6
    for dev in ("dome", "observingconditions", "safetymonitor"):
        assert finished[dev] < 0.4, finished


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
    camera = dict(device("Camera"), UniqueID="GUID-CAMERA")
    dome = dict(device("Dome"), UniqueID="GUID-DOME")
    coordinator = make_coordinator(FakeAlpaca(), [camera, dome])

    assert coordinator.device_uid(camera) == "GUID-CAMERA"
    assert coordinator.device_uid(dome) == "GUID-DOME"


def test_the_old_spelling_of_the_key_is_still_understood():
    dome = {"DeviceType": "Dome", "DeviceNumber": 0, "UniqueId": "OLD-SPELLING"}
    coordinator = make_coordinator(FakeAlpaca(), [dome])

    assert coordinator.device_uid(dome) == "OLD-SPELLING"


def test_the_fallback_id_contains_the_given_host_and_port():
    dome = dict(device("Dome"), UniqueID="")
    coordinator = make_coordinator(FakeAlpaca(), [dome], uid_host="10.0.0.5_32323")

    assert coordinator.device_uid(dome) == "10.0.0.5_32323_dome_0"


@pytest.mark.parametrize("unique_id", [None, "", "null", "None", "string"])
def test_a_missing_or_generic_unique_id_falls_back_to_the_server_and_device(unique_id):
    dome = dict(device("Dome", 2), UniqueID=unique_id)
    coordinator = make_coordinator(FakeAlpaca(), [dome], uid_host="192.168.1.9")

    assert coordinator.device_uid(dome) == "192.168.1.9_dome_2"


def test_devices_that_share_a_unique_id_get_different_entity_ids():
    dome = dict(device("Dome"), UniqueID="SAME")
    calibrator = dict(device("CoverCalibrator"), UniqueID="SAME")
    coordinator = make_coordinator(FakeAlpaca(), [dome, calibrator])
    coordinator.data = {}

    assert coordinator.device_uid(dome) != coordinator.device_uid(calibrator)
    first = cover_mod.AlpacaCover(coordinator, dome)
    second = cover_mod.AlpacaCover(coordinator, calibrator)
    assert first.unique_id != second.unique_id


def test_a_value_that_is_not_a_number_is_no_value():
    """Found live: a simulator answered NaN for the CCD temperature, Home Assistant refused the sensor state."""
    alpaca = FakeAlpaca()
    alpaca.set("camera", 0, "ccdtemperature", float("nan"))
    alpaca.set("camera", 0, "heatsinktemperature", float("inf"))
    alpaca.set("camera", 0, "coolerpower", 12.5)
    coordinator = make_coordinator(alpaca, [device("Camera")])

    run(coordinator.async_refresh())

    data = coordinator.data["camera_0"]
    assert "ccdtemperature" not in data and "heatsinktemperature" not in data
    assert data["coolerpower"] == 12.5


def test_a_failed_poll_says_what_failed_even_when_the_exception_has_no_text(monkeypatch):
    coordinator = make_coordinator(FakeAlpaca(), [device("Dome")])

    async def slow(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(coordinator, "_fetch_prop_task", slow)

    with pytest.raises(UpdateFailed, match="TimeoutError"):
        run(coordinator._async_update_data())

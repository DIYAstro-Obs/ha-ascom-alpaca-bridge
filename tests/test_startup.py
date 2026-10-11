"""A3: an Alpaca server that is not reachable at startup must not leave a half set up integration behind."""
import pathlib

import pytest

from ha_stubs import ConfigEntryNotReady
from helpers import FakeAlpaca, device, make_coordinator, run


def test_the_first_refresh_fails_while_the_server_is_unreachable():
    alpaca = FakeAlpaca()
    alpaca.up = False
    coordinator = make_coordinator(alpaca, [device("ObservingConditions"), device("SafetyMonitor")])

    with pytest.raises(ConfigEntryNotReady):
        run(coordinator.async_config_entry_first_refresh())


def test_a_later_outage_makes_the_update_fail_and_it_recovers():
    alpaca = FakeAlpaca()
    alpaca.set("safetymonitor", 0, "issafe", True)
    coordinator = make_coordinator(alpaca, [device("SafetyMonitor")])
    run(coordinator.async_refresh())
    assert coordinator.last_update_success
    assert coordinator.data["safetymonitor_0"]["issafe"] is True

    alpaca.up = False
    run(coordinator.async_refresh())
    assert not coordinator.last_update_success

    alpaca.up = True
    run(coordinator.async_refresh())
    assert coordinator.last_update_success
    assert coordinator.data["safetymonitor_0"]["issafe"] is True


def test_capabilities_are_not_cached_after_a_transport_error():
    alpaca = FakeAlpaca()
    alpaca.set("telescope", 0, "canpark", True)
    alpaca.set("telescope", 0, "canslewasync", True)
    alpaca.set("telescope", 0, "driverversion", "7.1")
    alpaca.fail_once("telescope", 0, "canpark")
    alpaca.fail_once("telescope", 0, "driverversion")
    coordinator = make_coordinator(alpaca, [device("Telescope")])

    run(coordinator.async_refresh())  # the server answers, but two requests are lost
    assert coordinator.last_update_success
    first = coordinator.data["telescope_0"]
    assert first["capabilities"]["canslewasync"] is True

    run(coordinator.async_refresh())
    second = coordinator.data["telescope_0"]
    assert second["capabilities"]["canpark"] is True
    assert second["driverversion"] == "7.1"


def test_a_property_the_server_does_not_implement_is_cached_as_false():
    alpaca = FakeAlpaca()
    alpaca.set("telescope", 0, "canslewasync", True)  # canpark: not implemented (ErrorNumber 1024)
    coordinator = make_coordinator(alpaca, [device("Telescope")])

    run(coordinator.async_refresh())
    run(coordinator.async_refresh())

    assert coordinator.data["telescope_0"]["capabilities"]["canpark"] is False
    assert alpaca.count("canpark") == 1  # answered definitively, asked once


def test_the_coordinator_does_not_use_the_deprecated_async_timeout():
    source = pathlib.Path(__file__).resolve().parents[1] / "custom_components/ascom_alpaca_bridge/coordinator.py"
    assert "async_timeout" not in source.read_text(encoding="utf-8")

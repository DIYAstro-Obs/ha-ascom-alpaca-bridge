"""A5: a command that does not work has to be visible to the caller (UI, automation), not only in the log."""
import pytest

from ha_stubs import HomeAssistantError
from helpers import FakeAlpaca, device, make_coordinator, run


def _coordinator(alpaca):
    return make_coordinator(alpaca, [device("Dome")])


def test_a_command_that_works_returns_true_and_sends_the_parameters():
    alpaca = FakeAlpaca()
    coordinator = _coordinator(alpaca)

    assert run(coordinator.send_command("dome", 0, "slewtoazimuth", {"Azimuth": "90"})) is True
    assert alpaca.last_put("slewtoazimuth")["Azimuth"] == "90"


@pytest.mark.parametrize("number, message", [(1024, "not implemented"), (1025, "invalid value"), (1035, "parked")])
def test_an_alpaca_error_raises(number, message):
    alpaca = FakeAlpaca()
    alpaca.put_errors["slewtoazimuth"] = (number, message)

    with pytest.raises(HomeAssistantError, match=message):
        run(_coordinator(alpaca).send_command("dome", 0, "slewtoazimuth", {"Azimuth": "90"}))


def test_an_unreachable_server_raises():
    alpaca = FakeAlpaca()
    alpaca.up = False

    with pytest.raises(HomeAssistantError):
        run(_coordinator(alpaca).send_command("dome", 0, "openshutter"))

"""Config flow: setup, errors, and the new reconfigure step (review stage 2: B13)."""
import importlib
import types

import pytest

from ha_stubs import AbortFlow, FakeHass
from helpers import FakeAlpaca, device, run

flow_mod = importlib.import_module("ascom_alpaca_bridge.config_flow")
const = importlib.import_module("ascom_alpaca_bridge.const")


def _server():
    alpaca = FakeAlpaca()
    alpaca.configured_devices = [
        {"DeviceType": "Camera", "DeviceNumber": 0, "DeviceName": "Cam", "UniqueID": "c0"},
        {"DeviceType": "Dome", "DeviceNumber": 0, "DeviceName": "Roof", "UniqueID": "d0"},
    ]
    return alpaca


def _flow(alpaca, *, entries=(), reconfigure=None):
    flow = flow_mod.AlpacaConfigFlow()
    flow.hass = FakeHass(alpaca)
    flow.configured_unique_ids = {e.unique_id for e in entries}
    flow.current_entries = list(entries)
    flow.reconfigure_entry = reconfigure
    return flow


def _entry(host="10.0.0.5", port=11111, devices=None, **extra):
    return types.SimpleNamespace(
        entry_id="e1",
        unique_id=f"{host}:{port}",
        data={const.CONF_HOST: host, const.CONF_PORT: port, const.CONF_DEVICES: devices or [], **extra},
    )


def test_manual_setup_creates_an_entry_with_the_selected_devices():
    flow = _flow(_server())

    form = run(flow.async_step_manual({"host": " 10.0.0.5 ", "port": 11111}))
    assert form["step_id"] == "select_devices"
    result = run(flow.async_step_select_devices({"devices": ["Dome_0"]}))

    assert result["type"] == "create_entry"
    assert result["title"] == "Test Server"
    assert result["data"][const.CONF_HOST] == "10.0.0.5"
    assert result["data"][const.CONF_UID_HOST] == "10.0.0.5_11111"  # host and port
    assert [d["DeviceType"] for d in result["data"][const.CONF_DEVICES]] == ["Dome"]


def test_an_unreachable_server_shows_an_error():
    alpaca = _server()
    alpaca.up = False

    result = run(_flow(alpaca).async_step_manual({"host": "10.0.0.5", "port": 11111}))

    assert result["step_id"] == "manual"
    assert result["errors"] == {"base": "cannot_connect"}


def test_a_server_that_is_already_configured_is_refused():
    flow = _flow(_server(), entries=[_entry()])

    with pytest.raises(AbortFlow):
        run(flow.async_step_manual({"host": "10.0.0.5", "port": 11111}))


def test_no_devices_selected_is_an_error():
    flow = _flow(_server())
    run(flow.async_step_manual({"host": "10.0.0.5", "port": 11111}))

    result = run(flow.async_step_select_devices({"devices": []}))

    assert result["errors"] == {"base": "no_devices_selected"}


def test_reconfigure_shows_the_current_address():
    entry = _entry("10.0.0.5", 11111)
    flow = _flow(_server(), entries=[entry], reconfigure=entry)

    form = run(flow.async_step_reconfigure())

    assert form["step_id"] == "reconfigure"


def test_reconfigure_updates_address_and_devices_and_keeps_the_uid_host():
    entry = _entry("10.0.0.5", 11111, devices=[{"DeviceType": "Camera", "DeviceNumber": 0}])
    flow = _flow(_server(), entries=[entry], reconfigure=entry)

    run(flow.async_step_reconfigure({"host": "10.0.0.77", "port": 11112}))
    result = run(flow.async_step_select_devices({"devices": ["Camera_0", "Dome_0"]}))

    assert result["reason"] == "reconfigure_successful"
    assert result["unique_id"] == "10.0.0.77:11112"
    updates = result["data_updates"]
    assert updates[const.CONF_HOST] == "10.0.0.77"
    assert updates[const.CONF_PORT] == 11112
    assert updates[const.CONF_UID_HOST] == "10.0.0.5"  # the identity of the entities does not move with the IP
    assert [d["DeviceType"] for d in updates[const.CONF_DEVICES]] == ["Camera", "Dome"]


def test_reconfigure_keeps_the_first_uid_host_over_several_changes():
    entry = _entry("10.0.0.77", 11111, **{const.CONF_UID_HOST: "10.0.0.5"})
    flow = _flow(_server(), entries=[entry], reconfigure=entry)

    run(flow.async_step_reconfigure({"host": "10.0.0.88", "port": 11111}))
    result = run(flow.async_step_select_devices({"devices": ["Camera_0"]}))

    assert result["data_updates"][const.CONF_UID_HOST] == "10.0.0.5"


def test_reconfigure_cannot_take_over_the_address_of_another_entry():
    mine = _entry("10.0.0.5", 11111)
    other = types.SimpleNamespace(entry_id="e2", unique_id="10.0.0.9:11111", data={})
    flow = _flow(_server(), entries=[mine, other], reconfigure=mine)

    result = run(flow.async_step_reconfigure({"host": "10.0.0.9", "port": 11111}))

    assert result == {"type": "abort", "reason": "already_configured"}


def test_reconfigure_may_keep_its_own_address():
    entry = _entry("10.0.0.5", 11111)
    flow = _flow(_server(), entries=[entry], reconfigure=entry)

    form = run(flow.async_step_reconfigure({"host": "10.0.0.5", "port": 11111}))

    assert form["step_id"] == "select_devices"

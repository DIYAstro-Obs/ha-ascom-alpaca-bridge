"""Config entry version 1 -> 2: the unique IDs of entities and devices move to the Alpaca UniqueID, so entity IDs
and history stay while the identity stops depending on host and port."""
import importlib
import types

from ha_stubs import FakeHass
from helpers import device, run

bridge = importlib.import_module("ascom_alpaca_bridge")
DOMAIN = "ascom_alpaca_bridge"


def _entry(devices, version=1, **extra):
    data = {"host": "10.0.0.5", "port": 11111, "devices": devices, **extra}
    return types.SimpleNamespace(entry_id="e1", title="Server", version=version, data=data)


def _hass():
    hass = FakeHass()
    return hass


def _unique_ids(hass):
    return {e.entity_id: e.unique_id for e in hass.entity_registry.entries.values()}


def test_entities_and_devices_move_to_the_unique_id():
    devices = [
        dict(device("Camera"), UniqueID="GUID-CAMERA"),
        dict(device("Switch"), UniqueID="GUID-SWITCH"),
        dict(device("Dome"), UniqueID=""),  # this server gives none for the dome
    ]
    hass = _hass()
    registry = hass.entity_registry
    registry.add("camera.cam", "10.0.0.5_camera_0_camera", "e1")
    registry.add("number.cam_bin_x", "10.0.0.5_camera_0_binx", "e1")
    registry.add("sensor.sw_value", "10.0.0.5_switch_0_3_value", "e1")
    registry.add("cover.roof", "10.0.0.5_dome_0_cover", "e1")
    registry.add("sensor.other", "10.0.0.5_camera_0_camerastate", "another-entry")
    hass.device_registry.add("dev-cam", [(DOMAIN, "10.0.0.5_camera_0")], config_entries=["e1"])
    hass.device_registry.add("dev-dome", [(DOMAIN, "10.0.0.5_dome_0")], config_entries=["e1"])
    entry = _entry(devices)

    assert run(bridge.async_migrate_entry(hass, entry)) is True

    ids = _unique_ids(hass)
    assert ids["camera.cam"] == "GUID-CAMERA_camera"
    assert ids["number.cam_bin_x"] == "GUID-CAMERA_binx"
    assert ids["sensor.sw_value"] == "GUID-SWITCH_3_value"
    assert ids["cover.roof"] == "10.0.0.5_dome_0_cover"  # no UniqueID: unchanged
    assert ids["sensor.other"] == "10.0.0.5_camera_0_camerastate"  # an entity of another entry stays
    assert hass.device_registry.devices["dev-cam"].identifiers == {(DOMAIN, "GUID-CAMERA")}
    assert hass.device_registry.devices["dev-dome"].identifiers == {(DOMAIN, "10.0.0.5_dome_0")}
    assert entry.version == 2


def test_the_migration_uses_the_host_of_the_first_setup():
    devices = [dict(device("Camera"), UniqueID="GUID-CAMERA")]
    hass = _hass()
    hass.entity_registry.add("camera.cam", "10.0.0.5_32323_camera_0_camera", "e1")
    entry = _entry(devices, uid_host="10.0.0.5_32323")

    run(bridge.async_migrate_entry(hass, entry))

    assert _unique_ids(hass)["camera.cam"] == "GUID-CAMERA_camera"


def test_devices_that_share_a_unique_id_keep_their_ids():
    devices = [dict(device("Dome"), UniqueID="SAME"), dict(device("CoverCalibrator"), UniqueID="SAME")]
    hass = _hass()
    hass.entity_registry.add("cover.roof", "10.0.0.5_dome_0_cover", "e1")
    hass.entity_registry.add("cover.flat", "10.0.0.5_covercalibrator_0_cover", "e1")

    run(bridge.async_migrate_entry(hass, _entry(devices)))

    assert _unique_ids(hass) == {
        "cover.roof": "10.0.0.5_dome_0_cover",
        "cover.flat": "10.0.0.5_covercalibrator_0_cover",
    }


def test_a_device_number_that_starts_like_another_is_not_confused():
    devices = [dict(device("Switch", 1), UniqueID="GUID-1"), dict(device("Switch", 10), UniqueID="GUID-10")]
    hass = _hass()
    hass.entity_registry.add("sensor.one", "10.0.0.5_switch_1_0_value", "e1")
    hass.entity_registry.add("sensor.ten", "10.0.0.5_switch_10_0_value", "e1")

    run(bridge.async_migrate_entry(hass, _entry(devices)))

    ids = _unique_ids(hass)
    assert ids["sensor.one"] == "GUID-1_0_value"
    assert ids["sensor.ten"] == "GUID-10_0_value"


def test_a_migrated_entry_is_left_alone():
    devices = [dict(device("Camera"), UniqueID="GUID-CAMERA")]
    hass = _hass()
    hass.entity_registry.add("camera.cam", "10.0.0.5_camera_0_camera", "e1")
    entry = _entry(devices, version=2)

    run(bridge.async_migrate_entry(hass, entry))

    assert _unique_ids(hass)["camera.cam"] == "10.0.0.5_camera_0_camera"


def test_running_it_twice_changes_nothing_more():
    devices = [dict(device("Camera"), UniqueID="GUID-CAMERA")]
    hass = _hass()
    hass.entity_registry.add("camera.cam", "10.0.0.5_camera_0_camera", "e1")
    entry = _entry(devices)

    run(bridge.async_migrate_entry(hass, entry))
    entry.version = 1  # as if it had been interrupted before the version was stored
    run(bridge.async_migrate_entry(hass, entry))

    assert _unique_ids(hass)["camera.cam"] == "GUID-CAMERA_camera"

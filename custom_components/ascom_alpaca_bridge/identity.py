"""Unique IDs of the devices: the Alpaca UniqueID when the server gives a usable one, otherwise one built from
the server and the device.

Before version 2 of the config entries the bridge read the key "UniqueId", but Alpaca (and every server) says
"UniqueID", so every device had the host based ID. The migration in __init__.py moves the entities to the
UniqueID; devices without a usable one keep the host based ID.
"""

# UniqueID values of servers that do not really provide one
GENERIC_UNIQUE_IDS = ("null", "none", "", "string")


def _alpaca_unique_id(device: dict) -> "str | None":
    uid = device.get("UniqueID") or device.get("UniqueId")
    if uid and str(uid).lower() not in GENERIC_UNIQUE_IDS:
        return str(uid)
    return None


def fallback_uid(device: dict, uid_host: str) -> str:
    """The ID built from the server and the device: `<host>_<type>_<number>`."""
    return f"{uid_host}_{device['DeviceType'].lower()}_{device['DeviceNumber']}"


def device_uid(device: dict, devices: list, uid_host: str) -> str:
    """The unique ID of `device` (one of `devices`, the devices of one server).

    The fallback is used when the server gives none, a generic one, or the same one for several devices
    (their entities would collide).
    """
    uid = _alpaca_unique_id(device)
    if uid is not None and sum(1 for other in devices if _alpaca_unique_id(other) == uid) == 1:
        return uid
    return fallback_uid(device, uid_host)

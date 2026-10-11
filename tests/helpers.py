"""Test helpers: a scripted Alpaca server behind an aiohttp-like session, and builders for the coordinator."""

from __future__ import annotations

import asyncio
import struct
from urllib.parse import parse_qs, urlparse

import ha_stubs
from ha_stubs import ClientConnectorError, FakeHass

import importlib

coordinator_mod = importlib.import_module("ascom_alpaca_bridge.coordinator")


class _Response:
    def __init__(self, status=200, payload=None, body=b""):
        self.status = status
        self._payload = payload
        self._body = body

    async def json(self):
        return self._payload

    async def read(self):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeAlpaca:
    """A scripted Alpaca server.

    values[(devtype, number, prop, arg)] is the answer of a GET (`arg` is the Id / SensorName query value or None),
    a missing key answers "not implemented" (ErrorNumber 1024). `up = False` makes every request fail at transport
    level; `fail_once` does that once for one property. PUT commands are recorded in `puts`.
    """

    def __init__(self):
        self.values: dict = {}
        self.up = True
        self._fail_once: set = set()
        self.requests: list = []
        self.puts: list = []  # (devtype, number, command, data)
        self.put_errors: dict = {}  # command -> (ErrorNumber, ErrorMessage)
        self.image: bytes | None = None

    # --- test side ---
    def set(self, devtype, number, prop, value, arg=None):
        self.values[(devtype.lower(), number, prop.lower(), arg)] = value

    def fail_once(self, devtype, number, prop, arg=None):
        self._fail_once.add((devtype.lower(), number, prop.lower(), arg))

    def count(self, prop) -> int:
        return sum(1 for r in self.requests if r[2] == prop)

    def last_put(self, command):
        matches = [p for p in self.puts if p[2] == command]
        return matches[-1][3] if matches else None

    # --- aiohttp side ---
    def _split(self, url):
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")  # api v1 <devtype> <number> <prop>
        query = {k.lower(): v[0] for k, v in parse_qs(parsed.query).items()}
        return parts[2].lower(), int(parts[3]), parts[4].lower(), query

    def get(self, url, headers=None, timeout=None):
        devtype, number, prop, query = self._split(url)
        arg = query.get("id") or query.get("sensorname")
        self.requests.append(("GET", devtype, prop, arg))
        if not self.up:
            raise ClientConnectorError("server is down")
        key = (devtype, number, prop, arg)
        if key in self._fail_once:
            self._fail_once.discard(key)
            raise ClientConnectorError("lost connection")
        if prop == "imagearray":
            return _Response(200, body=self.image or b"")
        if key in self.values:
            return _Response(200, {"Value": self.values[key], "ErrorNumber": 0, "ErrorMessage": ""})
        return _Response(200, {"ErrorNumber": 1024, "ErrorMessage": "not implemented"})

    def put(self, url, data=None, timeout=None):
        devtype, number, command, _ = self._split(url)
        if not self.up:
            raise ClientConnectorError("server is down")
        self.puts.append((devtype, number, command, dict(data or {})))
        if command in self.put_errors:
            number_, message = self.put_errors[command]
            return _Response(200, {"ErrorNumber": number_, "ErrorMessage": message})
        return _Response(200, {"ErrorNumber": 0, "ErrorMessage": ""})


def device(devtype: str, number: int = 0, name: str | None = None) -> dict:
    return {
        "DeviceType": devtype,
        "DeviceNumber": number,
        "DeviceName": name or f"{devtype} {number}",
        "UniqueId": f"uid-{devtype.lower()}-{number}",
        "ServerName": "Test Server",
    }


def make_coordinator(alpaca: FakeAlpaca, devices: list, **kwargs):
    hass = FakeHass(alpaca)
    coordinator = coordinator_mod.AlpacaDataUpdateCoordinator(hass, "10.0.0.5", 11111, devices, **kwargs)
    return coordinator


def run(coro):
    return asyncio.run(coro)


def image_bytes(pixels, dim1=4, dim2=3) -> bytes:
    """An Alpaca ImageBytes answer: 44 byte header, then 16 bit pixels (dim1 x dim2, column-major)."""
    assert len(pixels) == dim1 * dim2
    header = struct.pack("<11I", 1, 0, 0, 0, 44, 8, 8, 2, dim1, dim2, 0)
    return header + struct.pack(f"<{len(pixels)}H", *pixels)

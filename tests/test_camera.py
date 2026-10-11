"""A1: the camera entity has to fetch a new image after every exposure, not only the first one."""
import importlib

import pytest

from helpers import FakeAlpaca, device, image_bytes, make_coordinator, run

pytest.importorskip("PIL")

camera_mod = importlib.import_module("ascom_alpaca_bridge.camera")

DEV = device("Camera")


def _setup(alpaca):
    coordinator = make_coordinator(alpaca, [DEV])
    coordinator.data = {"camera_0": {"camerastate": 0, "imageready": True}}
    return coordinator, camera_mod.AlpacaCamera(coordinator, DEV)


def test_a_new_image_is_fetched_after_the_next_exposure():
    alpaca = FakeAlpaca()
    alpaca.image = image_bytes([i * 5000 for i in range(12)])
    coordinator, camera = _setup(alpaca)

    first = run(camera.async_camera_image())
    assert first and first[:2] == b"\xff\xd8"  # a JPEG

    # the next exposure runs: no image is ready, the last one stays visible
    coordinator.data["camera_0"].update(camerastate=2, imageready=False)
    assert run(camera.async_camera_image()) == first
    assert alpaca.count("imagearray") == 1

    # it is done: ImageReady is true again with a different picture
    alpaca.image = image_bytes([65535 - i * 5000 for i in range(12)])
    coordinator.data["camera_0"].update(camerastate=0, imageready=True)
    second = run(camera.async_camera_image())

    assert alpaca.count("imagearray") == 2
    assert second != first


def test_the_image_is_scaled_to_the_requested_size():
    from io import BytesIO

    from PIL import Image

    alpaca = FakeAlpaca()
    alpaca.image = image_bytes([i * 5000 for i in range(12)])  # 4 x 3 pixels
    coordinator, camera = _setup(alpaca)

    small = run(camera.async_camera_image(width=2, height=2))

    assert Image.open(BytesIO(small)).size[0] <= 2
    assert alpaca.count("imagearray") == 1
    full = run(camera.async_camera_image())
    assert Image.open(BytesIO(full)).size == (4, 3)


def test_the_same_image_is_not_fetched_again_while_it_stays_ready():
    alpaca = FakeAlpaca()
    alpaca.image = image_bytes([i * 5000 for i in range(12)])
    coordinator, camera = _setup(alpaca)

    run(camera.async_camera_image())
    run(camera.async_camera_image())
    run(camera.async_camera_image())

    assert alpaca.count("imagearray") == 1

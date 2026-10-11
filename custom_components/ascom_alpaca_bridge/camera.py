"""Camera platform for Alpaca Bridge."""
import asyncio
import io
import logging
import struct

import aiohttp
from PIL import Image

from homeassistant.components.camera import Camera
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .base import AlpacaEntity

LOGGER = logging.getLogger(__package__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the camera platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for device in coordinator.devices:
        if device["DeviceType"].lower() == "camera":
            entities.append(AlpacaCamera(coordinator, device))
    if entities:
        async_add_entities(entities)


def _image_bytes_to_jpeg(raw_data: bytes) -> "bytes | None":
    """Convert an Alpaca ImageBytes answer to a JPEG. CPU bound: runs in the executor, never in the event loop."""
    # Parse the 44-byte Little-Endian ArrayMetadataV1 (11 x uint32)
    header = struct.unpack_from("<11I", raw_data, 0)
    metadata_version = header[0]
    error_number = header[1]
    data_start = header[4]
    dim1 = header[8]   # X (width)
    dim2 = header[9]   # Y (height)
    dim3 = header[10]  # Z (channels)

    if error_number != 0 or metadata_version != 1:
        LOGGER.debug("Camera returned Alpaca error %s or an unknown header.", error_number)
        return None

    pixel_data = raw_data[data_start:]
    try:
        # The array is column-major: dim1 columns of dim2 pixels, so build it as (dim2, dim1) and transpose.
        if dim3 == 3:
            # 3 channels, assumed to be 8 bit
            image = Image.frombytes("RGB", (dim2, dim1), pixel_data)
        else:
            # The pixel width is taken from the data length (1: 8 bit, 2: 16 bit, 4: 32 bit integer).
            bytes_per_pixel = len(pixel_data) // (dim1 * dim2)
            modes = {1: "L", 2: "I;16", 4: "I"}
            if bytes_per_pixel not in modes:
                LOGGER.debug("Unsupported bytes per pixel = %s", bytes_per_pixel)
                return None
            image = Image.frombytes(modes[bytes_per_pixel], (dim2, dim1), pixel_data)

        image = image.transpose(Image.Transpose.TRANSPOSE)
        if image.mode in ("I;16", "I"):
            # Simple linear stretch to 8 bit (32 bit integers are assumed to hold 16 bit values).
            image = image.point(lambda i: i * (1 / 256)).convert("L")
        return _jpeg(image)
    except Exception as err:
        LOGGER.debug("Failed to decode ImageBytes: %s", err)
        return None


def _jpeg(image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def _scaled_jpeg(jpeg: bytes, width: "int | None", height: "int | None") -> bytes:
    """The JPEG shrunk to fit width x height (keeps the aspect ratio). Runs in the executor."""
    image = Image.open(io.BytesIO(jpeg))
    image.thumbnail((width or image.width, height or image.height))
    return _jpeg(image)


class AlpacaCamera(AlpacaEntity, Camera):
    """Representation of an ASCOM Alpaca Camera."""

    def __init__(self, coordinator, device):
        """Initialize."""
        super().__init__(coordinator, device)
        Camera.__init__(self)
        self._attr_name = f"Alpaca Camera {self.dev_num}"
        self._attr_unique_id = f"{super().unique_id}_camera"
        self._attr_is_streaming = False

        # The last image, whether it is the one of the exposure that is ready now, and the start time of that
        # exposure (LastExposureStartTime), which tells a new exposure even when nobody saw "not ready"
        self._last_image_data = None
        self._image_fetched = False
        self._image_key = None

    @property
    def brand(self) -> str | None:
        """Return the camera brand."""
        return self.coordinator.data.get(self.dev_key, {}).get("sensorname")

    @property
    def model(self) -> str | None:
        """Return the camera model."""
        return self.coordinator.data.get(self.dev_key, {}).get("sensorname") or "ASCOM Camera"

    def _handle_coordinator_update(self) -> None:
        """A poll that finds the camera not ready: the image that becomes ready next is a new one, also when
        nobody asked for the picture during the exposure."""
        if not self.coordinator.data.get(self.dev_key, {}).get("imageready"):
            self._image_fetched = False
        super()._handle_coordinator_update()

    async def async_camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        """Return bytes of camera image."""
        data = self.coordinator.data.get(self.dev_key, {})
        imageready = data.get("imageready")
        exposure = data.get("lastexposurestarttime")

        if not imageready:
            # An exposure is running (or nothing is known): the image that becomes ready next is a new one.
            self._image_fetched = False
            return await self._scaled(self._last_image_data, width, height)

        # ImageReady stays true until the next exposure: download once per exposure. The start time of the
        # exposure tells a new one when the poll did not see the camera busy (short exposures).
        new_exposure = exposure is not None and exposure != self._image_key
        if not self._image_fetched or self._last_image_data is None or new_exposure:
            raw_data = await self._download()
            if raw_data is None:
                return None
            jpeg = await self.coordinator.hass.async_add_executor_job(_image_bytes_to_jpeg, raw_data)
            if jpeg is None:
                return await self._scaled(self._last_image_data, width, height)
            self._last_image_data = jpeg
            self._image_fetched = True
            self._image_key = exposure

        return await self._scaled(self._last_image_data, width, height)

    async def _scaled(self, jpeg, width, height):
        if jpeg is None or not (width or height):
            return jpeg
        return await self.coordinator.hass.async_add_executor_job(_scaled_jpeg, jpeg, width, height)

    async def _download(self) -> "bytes | None":
        """Download the ImageBytes of the current image (a few retries for a busy server)."""
        url = f"http://{self.coordinator.host}:{self.coordinator.port}/api/v1/camera/{self.dev_num}/imagearray"
        headers = {"Accept": "application/imagebytes"}
        session = async_get_clientsession(self.coordinator.hass)

        retry_delay = 0.5
        max_retries = 3
        for attempt in range(max_retries):
            tid = self.coordinator.get_client_transaction_id()
            try:
                async with session.get(
                    f"{url}?ClientID=1&ClientTransactionID={tid}", headers=headers, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status != 200:
                        LOGGER.debug("Camera %s image fetch failed with status %s", self.name, response.status)
                        return None
                    raw_data = await response.read()
                if len(raw_data) < 44:
                    LOGGER.debug("Camera %s returned invalid ImageBytes (too short).", self.name)
                    return None
                return raw_data
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                if attempt < max_retries - 1:
                    LOGGER.debug("Camera %s image fetch failed (%s), retrying in %s seconds...", self.name, err, retry_delay)
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    LOGGER.warning("Camera %s image fetch failed after %s attempts: %s", self.name, max_retries, err)
                    return None
            except Exception as err:
                LOGGER.error("Camera %s unexpected error during image fetch: %s", self.name, err)
                return None
        return None

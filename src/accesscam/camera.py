"""UVC camera capture with manual exposure control and measured frame rate.

Advertised frame rates are frequently wrong, and auto-exposure is actively
harmful for IR dot tracking (it brightens the whole scene until room objects
rival the retroreflective marker). This module therefore forces MJPEG, exposes
manual exposure stepping, and measures the frame rate actually delivered.
"""

from __future__ import annotations

import sys
import time
from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import cv2
import numpy as np

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 30

# OpenCV's exposure scale is driver-dependent. On Windows/DirectShow and on
# V4L2 it is roughly log2(seconds), so -6 is ~15ms and -10 is ~1ms. Callers
# step through the range rather than relying on absolute values.
EXPOSURE_MIN = -13
EXPOSURE_MAX = 0

# The UVC convention replicated by most drivers: 0.25 selects manual exposure,
# 0.75 restores auto. Some Windows drivers instead use 1 and 0, so both are
# attempted and the result is read back.
_MANUAL_EXPOSURE_VALUES = (0.25, 1.0)
_AUTO_EXPOSURE_VALUES = (0.75, 0.0)


def default_backend() -> int:
    """Return the capture backend that behaves best on this platform."""
    if sys.platform == "win32":
        # DirectShow honours FOURCC and exposure requests that MSMF ignores.
        return cv2.CAP_DSHOW
    if sys.platform.startswith("linux"):
        return cv2.CAP_V4L2
    return cv2.CAP_ANY


@dataclass
class CameraSettings:
    """Requested capture configuration. What the driver grants may differ."""

    device: int = 0
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    backend: int | None = None

    def resolved_backend(self) -> int:
        return default_backend() if self.backend is None else self.backend


class CameraError(RuntimeError):
    """Raised when a camera cannot be opened or read."""


class CameraSource:
    """A single UVC camera, opened in MJPEG mode with manual exposure."""

    def __init__(self, settings: CameraSettings | None = None) -> None:
        self.settings = settings or CameraSettings()
        self._cap: cv2.VideoCapture | None = None
        self._frame_times: deque[float] = deque(maxlen=60)
        self._exposure = -6

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        cap = cv2.VideoCapture(self.settings.device, self.settings.resolved_backend())
        if not cap.isOpened():
            raise CameraError(
                f"Could not open camera device {self.settings.device}. "
                "Check that it is connected and not in use by another application."
            )

        # FOURCC must be set before the frame size, or the driver may fall back
        # to uncompressed YUY2 and silently drop to a fraction of the fps.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.height)
        cap.set(cv2.CAP_PROP_FPS, self.settings.fps)

        self._cap = cap
        self.disable_auto_exposure()
        self.set_exposure(self._exposure)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- capture -----------------------------------------------------------

    def read(self) -> np.ndarray | None:
        """Grab one frame, or None if the driver dropped it."""
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        self._frame_times.append(time.perf_counter())
        return frame

    @property
    def measured_fps(self) -> float:
        """Frame rate observed over the recent window, not the advertised one."""
        if len(self._frame_times) < 2:
            return 0.0
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return 0.0
        return (len(self._frame_times) - 1) / span

    # -- controls ----------------------------------------------------------

    def disable_auto_exposure(self) -> bool:
        """Switch to manual exposure. Returns whether the driver accepted it."""
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        for value in _MANUAL_EXPOSURE_VALUES:
            if self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value):
                return True
        return False

    def enable_auto_exposure(self) -> bool:
        """Restore auto exposure, for comparison during bring-up."""
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        for value in _AUTO_EXPOSURE_VALUES:
            if self._cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, value):
                return True
        return False

    def set_exposure(self, value: int) -> int:
        """Set exposure, clamped to the usable range. Returns the value applied."""
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        self._exposure = max(EXPOSURE_MIN, min(EXPOSURE_MAX, int(value)))
        self._cap.set(cv2.CAP_PROP_EXPOSURE, self._exposure)
        return self._exposure

    def step_exposure(self, delta: int) -> int:
        return self.set_exposure(self._exposure + delta)

    @property
    def exposure(self) -> int:
        """The exposure value most recently requested."""
        return self._exposure

    @property
    def actual_exposure(self) -> float:
        """What the driver reports back. Some backends silently clamp the range.

        Windows MSMF has been observed to accept a request for -10 and hold at
        -6, while DirectShow applies the full range - worth watching, since
        short exposures are what isolate the marker from room lighting.
        """
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        return self._cap.get(cv2.CAP_PROP_EXPOSURE)

    # -- diagnostics -------------------------------------------------------

    def actual_format(self) -> dict[str, object]:
        """Report what the driver actually granted, for the M1 checklist."""
        if self._cap is None:
            raise CameraError("Camera is not open. Call open() first.")
        fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip()
        return {
            "width": int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "codec": codec,
            "driver_fps": self._cap.get(cv2.CAP_PROP_FPS),
            "exposure": self._cap.get(cv2.CAP_PROP_EXPOSURE),
        }


def list_devices(max_index: int = 8) -> list[int]:
    """Probe for readable camera indices. Slow, so only used interactively."""
    backend = default_backend()
    found: list[int] = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                found.append(index)
        cap.release()
    return found

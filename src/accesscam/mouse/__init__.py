"""Cursor backends.

`windows` is imported lazily by `create_backend` so that importing this package
works on Linux and macOS, where `ctypes.wintypes` is unavailable - the tests
run on Linux in CI.
"""

from __future__ import annotations

import sys

from accesscam.mouse.base import (
    ABSOLUTE_RANGE,
    CursorController,
    MouseBackend,
    ScreenBounds,
    to_absolute,
)
from accesscam.mouse.fake import RecordingMouse

__all__ = [
    "ABSOLUTE_RANGE",
    "CursorController",
    "MouseBackend",
    "RecordingMouse",
    "ScreenBounds",
    "create_backend",
    "to_absolute",
]


def create_backend() -> MouseBackend:
    """Return the cursor backend for this platform."""
    if sys.platform == "win32":
        from accesscam.mouse.windows import WindowsMouse

        return WindowsMouse()
    raise NotImplementedError(
        f"No mouse backend for {sys.platform!r} yet. Linux (uinput) is M6, macOS is M7."
    )

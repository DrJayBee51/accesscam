"""Backend-independent pieces of cursor control.

Everything here is pure arithmetic so it can be tested on any platform. The
OS-specific plumbing lives in `windows.py`, which is imported lazily because
`ctypes.wintypes` does not exist off Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# SendInput does not take pixels. Absolute mouse coordinates are normalised
# into this range across the reference rectangle, which is the virtual desktop
# when MOUSEEVENTF_VIRTUALDESK is set.
ABSOLUTE_RANGE = 65535


@dataclass(frozen=True)
class ScreenBounds:
    """The virtual desktop, in physical pixels.

    `left` and `top` are frequently negative: any monitor placed above or to
    the left of the primary one pushes the origin into negative territory, and
    coordinate maths that assumes (0, 0) breaks there.
    """

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def clamp(self, x: float, y: float) -> tuple[float, float]:
        """Confine a point to the desktop rectangle.

        Note this is the bounding box, not the union of the monitors: an
        L-shaped or gapped arrangement leaves regions inside the box that are
        not on any screen. Windows itself refuses to park the cursor off-screen
        and snaps it to the nearest monitor, so clamping to the box is a safety
        net against runaway values rather than a guarantee of visibility.
        """
        cx = min(max(x, float(self.left)), float(self.right - 1))
        cy = min(max(y, float(self.top)), float(self.bottom - 1))
        return (cx, cy)


@runtime_checkable
class MouseBackend(Protocol):
    """The minimum a platform must provide to drive the cursor."""

    def bounds(self) -> ScreenBounds: ...

    def position(self) -> tuple[int, int]: ...

    def move_to(self, x: int, y: int) -> None: ...


def to_absolute(x: int, y: int, bounds: ScreenBounds) -> tuple[int, int]:
    """Map a screen pixel to SendInput's normalised absolute space.

    Subtracting the origin first is what makes this work on a desktop whose
    top-left is negative. Dividing by (extent - 1) rather than extent maps the
    last addressable pixel exactly onto ABSOLUTE_RANGE instead of falling one
    step short.

    Verified 2026-08-10 against a four-monitor mixed-DPI desktop: 16 of 16
    probe points, spread across every screen, landed on the exact pixel
    requested. Dividing by the extent instead of (extent - 1) lands 1px short
    on most points, so the -1 is load-bearing rather than cosmetic.
    """
    span_x = max(bounds.width - 1, 1)
    span_y = max(bounds.height - 1, 1)
    nx = round((x - bounds.left) * ABSOLUTE_RANGE / span_x)
    ny = round((y - bounds.top) * ABSOLUTE_RANGE / span_y)
    return (nx, ny)


class CursorController:
    """Moves the cursor by accumulated sub-pixel deltas.

    The cursor position is kept here as floats and only rounded on the way out.
    Reading the OS cursor back each frame would discard the fraction, and at 30
    frames a second any motion slower than one pixel per frame would be thrown
    away permanently - which is exactly the slow, deliberate movement needed to
    land on a small target.
    """

    def __init__(self, backend: MouseBackend) -> None:
        self._backend = backend
        self._bounds = backend.bounds()
        self._x = 0.0
        self._y = 0.0
        self._last_sent: tuple[int, int] | None = None
        self.sync()

    @property
    def bounds(self) -> ScreenBounds:
        return self._bounds

    @property
    def position(self) -> tuple[float, float]:
        """The internal sub-pixel position, not the OS cursor."""
        return (self._x, self._y)

    def sync(self) -> None:
        """Adopt the OS cursor position, discarding accumulated fraction.

        Call on unpause, or whenever the cursor may have been moved by other
        means, so the next delta is applied from where the cursor actually is.
        """
        self._bounds = self._backend.bounds()
        x, y = self._backend.position()
        self._x, self._y = self._bounds.clamp(float(x), float(y))
        self._last_sent = (round(self._x), round(self._y))

    def move_by(self, dx: float, dy: float) -> None:
        """Add a sub-pixel delta and move the cursor if the rounded pixel changed."""
        self._x, self._y = self._bounds.clamp(self._x + dx, self._y + dy)
        target = (round(self._x), round(self._y))
        # Skipping unchanged positions keeps a still head from issuing 30
        # redundant input events a second.
        if target != self._last_sent:
            self._backend.move_to(*target)
            self._last_sent = target

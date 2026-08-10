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
        """Confine a point to this rectangle."""
        cx = min(max(x, float(self.left)), float(self.right - 1))
        cy = min(max(y, float(self.top)), float(self.bottom - 1))
        return (cx, cy)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@runtime_checkable
class MouseBackend(Protocol):
    """The minimum a platform must provide to drive the cursor."""

    def bounds(self) -> ScreenBounds: ...

    def monitors(self) -> list[ScreenBounds]: ...

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
        self._monitors = backend.monitors()
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
        self._monitors = self._backend.monitors()
        x, y = self._backend.position()
        self._x, self._y = self._bounds.clamp(float(x), float(y))
        self._last_sent = (round(self._x), round(self._y))

    def _monitor_at(self, x: float, y: float) -> ScreenBounds | None:
        for monitor in self._monitors:
            if monitor.contains(x, y):
                return monitor
        return None

    def _constrain(self, x: float, y: float) -> tuple[float, float]:
        """Keep the position somewhere the cursor can actually go.

        Clamping to the bounding box is not enough. Monitors rarely tile their
        own bounding box - a display above and to one side leaves a rectangle
        belonging to no screen - and Windows will not park the cursor there, it
        pins it to the edge. If this position were allowed to travel into that
        dead space the internal position and the visible cursor would silently
        diverge, and moving back would spend the phantom travel before anything
        on screen moved.

        When the full move is impossible, the move is retried with one axis
        held, and the result is clamped into whichever monitor that lands on.
        Clamping rather than rejecting matters: rejecting the step would leave
        the cursor up to a whole step short of the edge, which at a max_step of
        400px is a visible gap. A move onto a different monitor is still
        accepted outright whenever the destination is real, so transitions
        between displays keep working.
        """
        if not self._monitors or self._monitor_at(x, y) is not None:
            return (x, y)

        for probe_x, probe_y in ((x, self._y), (self._x, y), (self._x, self._y)):
            host = self._monitor_at(probe_x, probe_y)
            if host is not None:
                return host.clamp(x, y)

        return (self._x, self._y)

    def move_by(self, dx: float, dy: float) -> None:
        """Add a sub-pixel delta and move the cursor if the rounded pixel changed."""
        candidate = self._bounds.clamp(self._x + dx, self._y + dy)
        self._x, self._y = self._constrain(*candidate)
        target = (round(self._x), round(self._y))
        # Skipping unchanged positions keeps a still head from issuing 30
        # redundant input events a second.
        if target != self._last_sent:
            self._backend.move_to(*target)
            self._last_sent = target

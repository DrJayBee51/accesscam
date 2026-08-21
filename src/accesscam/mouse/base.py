"""Backend-independent pieces of cursor control.

Everything here is pure arithmetic so it can be tested on any platform. The
OS-specific plumbing lives in `windows.py`, which is imported lazily because
`ctypes.wintypes` does not exist off Windows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from accesscam.log import log

# How far past a hard edge the tracked position may travel while the visible
# cursor stays pinned there, in cursor pixels.
#
# This is the head-tracking equivalent of lifting a mouse and setting it down
# again. A head has no lift, so the only way to re-bias - to end a long reach
# without being left leaning - is to push the cursor into an edge, keep going
# to bank some travel, and then move back through that bank while the cursor
# stays put. Moving past centre before the cursor releases is the point.
#
# It applies only where the cursor genuinely cannot go further. Boundaries
# between two displays are crossable, so nothing is banked there and crossing
# stays immediate.
#
# Off by default. Banking is exactly the behaviour that made the cursor feel
# unresponsive at the top of a display with nothing above it - the difference
# between a clutch and a fault is whether the user meant to push into the edge,
# and the code cannot tell. Opt in by setting `clutch` in the config; 600 is a
# reasonable first try, which at the measured gains is about 20px of head
# movement.
DEFAULT_CLUTCH = 0.0

# SendInput does not take pixels. Absolute mouse coordinates are normalised
# into this range across the reference rectangle, which is the virtual desktop
# when MOUSEEVENTF_VIRTUALDESK is set.
ABSOLUTE_RANGE = 65535

# How far the cursor may differ from where AccessCam last saw it before that
# counts as somebody else having moved it. Rounding and DPI scaling can shift a
# read-back by a pixel, and a false positive stutters tracking for no reason.
FOREIGN_MOVE_TOLERANCE = 2


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

    def __init__(
        self,
        backend: MouseBackend,
        clutch: float = DEFAULT_CLUTCH,
    ) -> None:
        self._backend = backend
        self._bounds = backend.bounds()
        self._monitors = backend.monitors()
        self.clutch = clutch
        # The tracked position, which may sit up to `clutch` beyond the edge.
        self._x = 0.0
        self._y = 0.0
        # Where the cursor actually is: the tracked position with any banked
        # over-travel removed.
        self._cursor = (0.0, 0.0)
        self._last_sent: tuple[int, int] | None = None
        # Where the cursor was last seen to be, as opposed to where it was
        # last sent. The two differ whenever something else moves it.
        self._observed: tuple[int, int] | None = None
        self.sync()

    @property
    def bounds(self) -> ScreenBounds:
        return self._bounds

    @property
    def position(self) -> tuple[float, float]:
        """Where the cursor is, sub-pixel. Excludes any banked over-travel."""
        return self._cursor

    @property
    def tracked(self) -> tuple[float, float]:
        """The tracked position, which may be up to `clutch` beyond an edge."""
        return (self._x, self._y)

    @property
    def banked(self) -> tuple[float, float]:
        """How much over-travel is currently held against an edge."""
        return (self._x - self._cursor[0], self._y - self._cursor[1])

    def sync(self) -> None:
        """Adopt the OS cursor position, discarding accumulated fraction.

        Call on unpause, or whenever the cursor may have been moved by other
        means, so the next delta is applied from where the cursor actually is.
        """
        self._bounds = self._backend.bounds()
        self._monitors = self._backend.monitors()
        try:
            x, y = self._backend.position()
        except OSError as exc:
            # Asking where the cursor is fails when the input desktop is not
            # ours: during logon, and whenever the secure desktop is up for a
            # UAC prompt. Refusing to start over it would mean the one launch
            # that has to succeed unattended is the one most likely to fail.
            # The middle of the desktop is a fine guess, and the next unpause
            # syncs properly anyway.
            log.warning("could not read the cursor position (%s) - assuming centre", exc)
            x = self._bounds.left + self._bounds.width // 2
            y = self._bounds.top + self._bounds.height // 2
        self._x, self._y = self._bounds.clamp(float(x), float(y))
        self._cursor = (self._x, self._y)
        self._last_sent = (round(self._x), round(self._y))
        self._observed = (x, y)

    def _observe(self) -> None:
        """Remember where the cursor actually ended up after we moved it.

        Read back rather than assumed: Windows pins the cursor to a screen edge
        and clamps into regions no monitor covers, so where it lands is not
        always where it was sent. Comparing against the *observed* position is
        what makes foreign movement detectable without every clamp looking like
        somebody else's mouse.
        """
        try:
            self._observed = self._backend.position()
        except OSError:
            self._observed = None

    def foreign_movement(self, tolerance: int = FOREIGN_MOVE_TOLERANCE) -> bool:
        """Whether something other than AccessCam has moved the cursor.

        No hook and no injected-event flag: the cursor's own position answers
        it. AccessCam knows where it last saw the cursor, so anything else that
        moved it - a real mouse, a QuadStick, another program - shows up as a
        discrepancy, and AccessCam's own movement never does.

        The tolerance exists because rounding and DPI scaling can shift the
        read-back by a pixel, and a false positive here means head tracking
        stutters for no reason.
        """
        if self._observed is None:
            return False
        try:
            x, y = self._backend.position()
        except OSError:
            return False
        return abs(x - self._observed[0]) > tolerance or abs(y - self._observed[1]) > tolerance

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

        # Probes are taken against the last *cursor* position, not the tracked
        # one: the tracked position may be sitting out past an edge holding
        # banked over-travel, which is not anywhere the cursor has ever been.
        last_x, last_y = self._cursor
        for probe_x, probe_y in ((x, last_y), (last_x, y), (last_x, last_y)):
            host = self._monitor_at(probe_x, probe_y)
            if host is not None:
                return host.clamp(x, y)

        return self._cursor

    def move_by(self, dx: float, dy: float) -> None:
        """Add a sub-pixel delta and move the cursor if the rounded pixel changed.

        The tracked position is allowed to run past a hard edge by up to
        `clutch`, while the cursor stays pinned. Moving back spends that bank
        before the cursor follows, which is what lets the head return past
        centre without dragging the cursor off the edge with it.
        """
        self._x += dx
        self._y += dy

        self._cursor = self._constrain(*self._bounds.clamp(self._x, self._y))

        # Bound the bank, or a long push would take just as long to unwind.
        limit = max(self.clutch, 0.0)
        self._x = min(max(self._x, self._cursor[0] - limit), self._cursor[0] + limit)
        self._y = min(max(self._y, self._cursor[1] - limit), self._cursor[1] + limit)

        target = (round(self._cursor[0]), round(self._cursor[1]))
        # Skipping unchanged positions keeps a still head from issuing 30
        # redundant input events a second.
        if target != self._last_sent:
            self._backend.move_to(*target)
            self._last_sent = target
        self._observe()

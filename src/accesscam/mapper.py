"""Turn marker motion into cursor motion.

Two mappings, deliberately separate types rather than one class with a mode
flag, because they do genuinely different things: the relative mapper answers
"how far should the cursor move", the absolute one answers "where should the
cursor be".

Relative is the primary path. Its mapping is not fixed, so overshooting a
target is recoverable - move back and take a second pass - which is how the
SmartNav this replaces is used. Absolute is best-effort: a miss stays missed,
and on a multi-monitor desktop the bounding box contains regions that are on no
screen at all, so it needs a deliberate choice of target rectangle rather than
a naive map onto everything.

Both expect a marker position that has *already* been smoothed, in camera
pixels. Filtering before the gain keeps the filter's tuning independent of the
gain: retune one and the other still holds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from accesscam.mouse.base import ScreenBounds

# Derived from the M1 bring-up run: 82.8 x 44.3px of marker travel across one
# 2560x1440 screen. Provisional - travel measures how far the user moved their
# head, not a property of the camera, so it varies between sessions and wants
# per-user calibration rather than being treated as a constant.
DEFAULT_H_GAIN = 31.0
DEFAULT_V_GAIN = 32.0

# A tracking glitch should not fling the cursor across the desktop. The tracker
# already refuses candidates more than max_jump (120px) from the last position,
# which at these gains is still ~3700px of cursor travel in a single frame.
# Clamping the step keeps a bad frame recoverable; at 30fps this ceiling still
# allows roughly 12000px/s, far quicker than anyone moves deliberately.
DEFAULT_MAX_STEP = 400.0


@dataclass
class MapperSettings:
    """Tuning for the relative mapping."""

    h_gain: float = DEFAULT_H_GAIN
    v_gain: float = DEFAULT_V_GAIN
    # The camera faces the user, so image X runs opposite to head motion: turn
    # right and the marker travels left across the sensor. Y usually needs no
    # flip, since up in the image and up on screen both mean a smaller
    # coordinate. Both depend on final mounting - confirm empirically.
    invert_x: bool = True
    invert_y: bool = False
    # Off by default. A dead zone is the usual way to stop jitter creeping the
    # cursor, but the One Euro filter upstream already suppresses that, and a
    # hard threshold has a nasty side effect: slow deliberate movement falls
    # below it and is discarded entirely, which is exactly the motion needed to
    # land on a small target.
    dead_zone: float = 0.0
    max_step: float = DEFAULT_MAX_STEP


class RelativeMapper:
    """Marker displacement between frames becomes cursor displacement."""

    def __init__(self, settings: MapperSettings | None = None) -> None:
        self.settings = settings or MapperSettings()
        self._last: tuple[float, float] | None = None

    def reset(self) -> None:
        """Forget the previous position, so the next frame produces no motion."""
        self._last = None

    def update(self, position: tuple[float, float] | None) -> tuple[float, float]:
        """Return the cursor delta for this frame. `None` means the marker was lost.

        The frame after an acquisition always yields (0, 0). Without that, a
        marker reacquired somewhere else in frame - the user looked away and
        back, or the track briefly dropped - would produce one enormous
        displacement and throw the cursor across the desktop.
        """
        if position is None:
            self._last = None
            return (0.0, 0.0)

        previous, self._last = self._last, position
        if previous is None:
            return (0.0, 0.0)

        dx = position[0] - previous[0]
        dy = position[1] - previous[1]

        if math.hypot(dx, dy) < self.settings.dead_zone:
            return (0.0, 0.0)

        if self.settings.invert_x:
            dx = -dx
        if self.settings.invert_y:
            dy = -dy

        return _clamp_step(
            dx * self.settings.h_gain,
            dy * self.settings.v_gain,
            self.settings.max_step,
        )


class AbsoluteMapper:
    """Marker position in frame becomes cursor position within a target rectangle.

    The target is one screen, not the whole virtual desktop: mapping onto the
    bounding box of a multi-monitor arrangement aims at coordinates that may
    not be on any display.
    """

    def __init__(
        self,
        frame_size: tuple[int, int],
        target: ScreenBounds,
        invert_x: bool = True,
        invert_y: bool = False,
    ) -> None:
        self.frame_width, self.frame_height = frame_size
        self.target = target
        self.invert_x = invert_x
        self.invert_y = invert_y

    def update(self, position: tuple[float, float] | None) -> tuple[float, float] | None:
        """Return the cursor position for this frame, or None if the marker was lost."""
        if position is None:
            return None

        fx = _unit(position[0], self.frame_width)
        fy = _unit(position[1], self.frame_height)
        if self.invert_x:
            fx = 1.0 - fx
        if self.invert_y:
            fy = 1.0 - fy

        x = self.target.left + fx * (self.target.width - 1)
        y = self.target.top + fy * (self.target.height - 1)
        return self.target.clamp(x, y)


def _unit(value: float, extent: int) -> float:
    """Position within a frame axis as 0.0-1.0, clamped to the frame."""
    if extent <= 1:
        return 0.0
    return min(max(value / (extent - 1), 0.0), 1.0)


def _clamp_step(dx: float, dy: float, limit: float) -> tuple[float, float]:
    """Bound the step length, scaling both axes so the direction is preserved."""
    if limit <= 0.0:
        return (dx, dy)
    magnitude = math.hypot(dx, dy)
    if magnitude <= limit:
        return (dx, dy)
    scale = limit / magnitude
    return (dx * scale, dy * scale)

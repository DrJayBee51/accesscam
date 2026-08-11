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
# but at a gain of 100 that is still ~12000px of cursor travel in one frame, so
# a ceiling is still worth having.
#
# It has to sit well above real movement, though. At 400 it was reached by a
# marker moving only 4px per frame - about 120 marker px/s - so any head sweep
# quicker than roughly 0.7s was truncated, and a fast sweep crossed one monitor
# where it should have crossed nearly three. Whatever the ceiling, the excess
# is now carried into the following frame rather than discarded, so the clamp
# limits how fast the cursor moves without changing how far it goes.
DEFAULT_MAX_STEP = 2500.0

# How many extra frames of held-back movement may be carried. Enough that a
# gesture a few times quicker than the ceiling still arrives in full, few
# enough that a wild tracking jump is truncated rather than delivered as a
# long slide.
CARRY_FRAMES = 2.0


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
        # Diagnostics. max_step exists to catch a tracking glitch, but set too
        # low it silently truncates real movement instead - and because the
        # excess is discarded rather than carried, a fast gesture then travels
        # less than a slow one covering the same distance. Counting the clips
        # makes that visible rather than a matter of opinion.
        self.steps = 0
        self.clipped = 0
        self.peak_demand = 0.0
        self._residual = (0.0, 0.0)

    def reset(self) -> None:
        """Forget the previous position, so the next frame produces no motion."""
        self._last = None
        self._residual = (0.0, 0.0)

    def update(self, position: tuple[float, float] | None) -> tuple[float, float]:
        """Return the cursor delta for this frame. `None` means the marker was lost.

        The frame after an acquisition always yields (0, 0). Without that, a
        marker reacquired somewhere else in frame - the user looked away and
        back, or the track briefly dropped - would produce one enormous
        displacement and throw the cursor across the desktop.
        """
        if position is None:
            self._last = None
            self._residual = (0.0, 0.0)
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

        step_x = dx * self.settings.h_gain
        step_y = dy * self.settings.v_gain

        demand = math.hypot(step_x, step_y)
        self.steps += 1
        self.peak_demand = max(self.peak_demand, demand)
        if self.settings.max_step > 0.0 and demand > self.settings.max_step:
            self.clipped += 1

        # Anything the clamp holds back is carried into the next frame instead
        # of being thrown away. Discarding it made a fast gesture travel less
        # than a slow one over the same ground, which is the one thing a
        # pointer must never do. The carry is itself bounded, so a genuine
        # tracking glitch is still truncated rather than paid out over the
        # following second.
        limit = self.settings.max_step
        wanted_x = step_x + self._residual[0]
        wanted_y = step_y + self._residual[1]
        moved = _clamp_step(wanted_x, wanted_y, limit)
        self._residual = _clamp_step(wanted_x - moved[0], wanted_y - moved[1], limit * CARRY_FRAMES)
        return moved


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

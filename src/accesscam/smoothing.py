"""One Euro filter — speed-adaptive smoothing for the marker position.

A fixed low-pass filter forces an unwinnable trade: enough smoothing to settle
the cursor at rest adds enough lag to make fast movement feel like dragging the
pointer through treacle. One Euro escapes it by varying its cutoff with speed -
heavy smoothing while nearly still, progressively less as the marker moves - so
rest is calm and motion stays responsive.

Casiez, Roussel & Vogel (2012), "1€ Filter: A Simple Speed-based Low-pass
Filter for Noisy Input in Interactive Systems".

This filters the marker position in *camera pixels*, upstream of the mapper's
gain. Filtering after the gain would make these cutoffs gain-dependent: change
a gain and the filter would need retuning. In camera pixels the tuning holds
regardless of how the cursor is scaled.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

# Tuned by replaying the measured M1 signal - 0.073 x 0.045px of jitter at rest
# - through the full smoother/mapper/cursor chain at a gain of 31px/px.
# Against unfiltered input this cuts cursor noise 5x (2.26 -> 0.45px standard
# deviation), shrinks the resting excursion 3.6x (15.2 -> 4.2px) and drops the
# input-event rate from 97% of frames to 22%, while keeping lag below one frame
# for everything but the very slowest movement: 69ms at 10px/s, 25ms at 30px/s,
# 7.8ms at 100px/s, 2.0ms at 400px/s.
#
# Below a min_cutoff of about 0.3 the resting excursion stops improving - what
# remains is low-frequency wander inside the passband - while lag keeps growing,
# so there is nothing to buy by going lower.
DEFAULT_MIN_CUTOFF = 0.3
DEFAULT_BETA = 0.20
# The derivative is itself noisy, so it gets its own gentle low-pass. 1.0Hz is
# the value the paper recommends and there has been no reason to move it.
DEFAULT_D_CUTOFF = 1.0

# A dropped USB frame should not be treated as a long quiet interval, which
# would let the filter snap. Clamp the timestep to something plausible.
MAX_TIMESTEP = 0.2


@dataclass
class SmoothingSettings:
    """Tuning for the One Euro filter.

    `min_cutoff` sets the calm: lower means steadier at rest and more lag.
    `beta` sets how fast the filter gets out of the way as the marker speeds
    up: higher means more responsive to real movement but less noise rejection
    during it. Tune min_cutoff first with beta at 0, then raise beta until fast
    movement stops feeling delayed.
    """

    min_cutoff: float = DEFAULT_MIN_CUTOFF
    beta: float = DEFAULT_BETA
    d_cutoff: float = DEFAULT_D_CUTOFF


def _alpha(cutoff: float, dt: float) -> float:
    """Smoothing factor for a first-order low-pass at this cutoff and timestep."""
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class _LowPass:
    """First-order low-pass holding its own previous output."""

    def __init__(self) -> None:
        self.value: float | None = None

    def reset(self) -> None:
        self.value = None

    def apply(self, sample: float, alpha: float) -> float:
        if self.value is None:
            self.value = sample
        else:
            self.value = alpha * sample + (1.0 - alpha) * self.value
        return self.value


class OneEuroFilter:
    """Speed-adaptive low-pass over a single axis."""

    def __init__(self, settings: SmoothingSettings | None = None) -> None:
        self.settings = settings or SmoothingSettings()
        self._value = _LowPass()
        self._derivative = _LowPass()
        self._last_sample: float | None = None
        self._last_time: float | None = None

    def reset(self) -> None:
        self._value.reset()
        self._derivative.reset()
        self._last_sample = None
        self._last_time = None

    def filter(self, sample: float, timestamp: float) -> float:
        if self._last_time is None or self._last_sample is None:
            self._last_sample = sample
            self._last_time = timestamp
            return self._value.apply(sample, 1.0)

        dt = min(max(timestamp - self._last_time, 1e-6), MAX_TIMESTEP)

        speed = (sample - self._last_sample) / dt
        smoothed_speed = self._derivative.apply(speed, _alpha(self.settings.d_cutoff, dt))

        cutoff = self.settings.min_cutoff + self.settings.beta * abs(smoothed_speed)
        result = self._value.apply(sample, _alpha(cutoff, dt))

        self._last_sample = sample
        self._last_time = timestamp
        return result


class PointSmoother:
    """One Euro applied to a 2D marker position.

    The axes are filtered independently, as in the original 1D formulation.
    That is deliberate rather than incidental: a fast horizontal sweep then
    relaxes smoothing on X while Y stays calm, so off-axis noise is not
    unlocked by motion that has nothing to do with it.
    """

    def __init__(self, settings: SmoothingSettings | None = None) -> None:
        self.settings = settings or SmoothingSettings()
        self._x = OneEuroFilter(self.settings)
        self._y = OneEuroFilter(self.settings)

    def reset(self) -> None:
        self._x.reset()
        self._y.reset()

    def update(
        self,
        position: tuple[float, float] | None,
        timestamp: float | None = None,
    ) -> tuple[float, float] | None:
        """Smooth one sample. `None` means the marker was lost, and resets the filter.

        Resetting on loss matters: without it, a marker reacquired elsewhere
        would be blended against a stale position and the smoothed point would
        slide across the gap over the following frames.
        """
        if position is None:
            self.reset()
            return None

        now = time.monotonic() if timestamp is None else timestamp
        return (self._x.filter(position[0], now), self._y.filter(position[1], now))

"""One Euro filter tests. Timestamps are supplied explicitly so they are
deterministic and do not depend on wall-clock timing."""

import random
import statistics

import pytest

from accesscam.smoothing import MAX_TIMESTEP, OneEuroFilter, PointSmoother, SmoothingSettings

FPS = 30.0


def steady(filt: OneEuroFilter, value: float, frames: int, start: float = 0.0) -> float:
    """Feed a constant value and return the settled output."""
    out = value
    for i in range(frames):
        out = filt.filter(value, start + i / FPS)
    return out


def ramp_lag(settings: SmoothingSettings, velocity: float, frames: int = 120) -> float:
    """Steady-state positional lag, in seconds, at a constant velocity."""
    smoother = PointSmoother(settings)
    errors = []
    for i in range(frames):
        x = 100.0 + velocity * i / FPS
        smoothed = smoother.update((x, 100.0), i / FPS)
        if i >= frames // 2:
            errors.append(x - smoothed[0])
    return statistics.mean(errors) / velocity


def test_first_sample_passes_through_unchanged():
    filt = OneEuroFilter()

    assert filt.filter(42.0, 0.0) == pytest.approx(42.0)


def test_constant_input_settles_on_that_value():
    filt = OneEuroFilter()

    assert steady(filt, 7.0, 120) == pytest.approx(7.0, abs=1e-6)


def test_noise_is_attenuated():
    random.seed(3)
    settings = SmoothingSettings()
    smoother = PointSmoother(settings)

    raw, smoothed = [], []
    for i in range(600):
        sample = 100.0 + random.gauss(0.0, 0.073)
        raw.append(sample)
        smoothed.append(smoother.update((sample, 100.0), i / FPS)[0])

    assert statistics.pstdev(smoothed) < statistics.pstdev(raw) / 3.0


def test_faster_movement_gets_less_lag():
    # The whole point of One Euro: the cutoff rises with speed, so lag falls as
    # movement gets faster. A fixed low-pass would show identical lag at both.
    settings = SmoothingSettings()

    assert ramp_lag(settings, 400.0) < ramp_lag(settings, 30.0) / 5.0


def test_beta_zero_gives_speed_independent_lag():
    # With beta at zero this degenerates to a plain low-pass, which is the
    # behaviour the adaptive cutoff exists to avoid.
    settings = SmoothingSettings(beta=0.0)

    slow = ramp_lag(settings, 30.0)
    fast = ramp_lag(settings, 400.0)

    assert fast == pytest.approx(slow, rel=0.1)


def test_higher_beta_reduces_lag():
    calm = ramp_lag(SmoothingSettings(beta=0.05), 100.0)
    responsive = ramp_lag(SmoothingSettings(beta=0.40), 100.0)

    assert responsive < calm


def test_lost_marker_resets_the_filter():
    smoother = PointSmoother()
    for i in range(60):
        smoother.update((100.0, 100.0), i / FPS)

    assert smoother.update(None, 2.0) is None

    # Reacquired elsewhere: the first sample after a reset is passed straight
    # through, rather than being blended against the stale position.
    assert smoother.update((500.0, 300.0), 2.1) == pytest.approx((500.0, 300.0))


def test_reset_clears_history():
    smoother = PointSmoother()
    for i in range(60):
        smoother.update((100.0, 100.0), i / FPS)
    smoother.reset()

    assert smoother.update((250.0, 250.0), 5.0) == pytest.approx((250.0, 250.0))


def test_a_long_gap_is_clamped():
    # A dropped USB frame must not be read as a long quiet interval, which
    # would drive alpha to 1 and let the filter snap to the raw sample.
    filt = OneEuroFilter()
    filt.filter(100.0, 0.0)
    filt.filter(100.0, 1 / FPS)

    jumped = filt.filter(200.0, 1 / FPS + 30.0)

    unclamped = OneEuroFilter()
    unclamped.filter(100.0, 0.0)
    unclamped.filter(100.0, 1 / FPS)
    expected_ceiling = unclamped.filter(200.0, 1 / FPS + MAX_TIMESTEP)

    assert jumped == pytest.approx(expected_ceiling)
    assert jumped < 200.0


def test_axes_are_filtered_independently():
    # A fast sweep on X must not unlock smoothing on Y, or off-axis noise
    # would be admitted by motion that has nothing to do with it.
    random.seed(5)
    smoother = PointSmoother()

    outputs = []
    for i in range(120):
        x = 100.0 + 400.0 * i / FPS
        y = 100.0 + random.gauss(0.0, 0.073)
        outputs.append(smoother.update((x, y), i / FPS)[1])

    assert statistics.pstdev(outputs[60:]) < 0.03


def test_timestamps_default_to_the_clock():
    smoother = PointSmoother()

    assert smoother.update((10.0, 20.0)) == pytest.approx((10.0, 20.0))
    assert smoother.update((10.0, 20.0)) is not None

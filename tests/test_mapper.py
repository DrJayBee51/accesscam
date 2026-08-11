"""Mapper tests. Pure arithmetic, so they run anywhere."""

import math

import pytest

from accesscam.mapper import CARRY_FRAMES, AbsoluteMapper, MapperSettings, RelativeMapper
from accesscam.mouse.base import ScreenBounds

PRIMARY = ScreenBounds(left=0, top=0, width=2560, height=1440)


def test_first_frame_after_acquisition_produces_no_motion():
    mapper = RelativeMapper()

    assert mapper.update((100.0, 100.0)) == (0.0, 0.0)


def test_displacement_is_scaled_by_the_per_axis_gains():
    mapper = RelativeMapper(MapperSettings(h_gain=10.0, v_gain=4.0, invert_x=False))
    mapper.update((100.0, 100.0))

    dx, dy = mapper.update((103.0, 105.0))

    assert dx == pytest.approx(30.0)
    assert dy == pytest.approx(20.0)


def test_inversion_flags_flip_each_axis():
    settings = MapperSettings(h_gain=1.0, v_gain=1.0, invert_x=True, invert_y=True)
    mapper = RelativeMapper(settings)
    mapper.update((100.0, 100.0))

    assert mapper.update((110.0, 90.0)) == pytest.approx((-10.0, 10.0))


def test_x_is_inverted_by_default_and_y_is_not():
    # The camera faces the user, so image X runs opposite to head motion.
    mapper = RelativeMapper(MapperSettings(h_gain=1.0, v_gain=1.0))
    mapper.update((100.0, 100.0))

    dx, dy = mapper.update((110.0, 110.0))

    assert dx < 0
    assert dy > 0


def test_reacquisition_elsewhere_does_not_fling_the_cursor():
    # The marker is lost and comes back on the far side of the frame. Without
    # the reset this would be one enormous displacement.
    mapper = RelativeMapper()
    mapper.update((100.0, 100.0))
    mapper.update((105.0, 100.0))

    mapper.update(None)
    assert mapper.update((600.0, 400.0)) == (0.0, 0.0)

    # Tracking resumes normally from the new position.
    dx, _ = mapper.update((601.0, 400.0))
    assert dx != 0.0


def test_losing_the_marker_reports_no_motion():
    mapper = RelativeMapper()
    mapper.update((100.0, 100.0))

    assert mapper.update(None) == (0.0, 0.0)


def test_reset_suppresses_the_next_delta():
    mapper = RelativeMapper()
    mapper.update((100.0, 100.0))
    mapper.reset()

    assert mapper.update((150.0, 150.0)) == (0.0, 0.0)


def test_dead_zone_is_disabled_by_default():
    # Slow deliberate movement must survive: it is how small targets are hit.
    mapper = RelativeMapper(MapperSettings(h_gain=10.0, v_gain=10.0, invert_x=False))
    mapper.update((100.0, 100.0))

    dx, _ = mapper.update((100.05, 100.0))

    assert dx == pytest.approx(0.5)


def test_dead_zone_suppresses_small_motion_when_enabled():
    settings = MapperSettings(h_gain=10.0, v_gain=10.0, invert_x=False, dead_zone=1.0)
    mapper = RelativeMapper(settings)
    mapper.update((100.0, 100.0))

    assert mapper.update((100.5, 100.0)) == (0.0, 0.0)
    assert mapper.update((102.5, 100.0)) != (0.0, 0.0)


def travel(mapper, position, frames):
    """Total horizontal cursor movement, letting any carry drain."""
    total = 0.0
    for _ in range(frames):
        total += mapper.update(position)[0]
        position = (position[0], position[1])
    return total


def test_a_quick_gesture_covers_the_same_ground_as_a_slow_one():
    # The reported symptom: a quick sweep crossed one monitor where the same
    # motion on a SmartNav crossed 2.5. The clamp discarded the excess, so
    # moving fast covered less ground than moving slowly - the one thing a
    # pointer must never do.
    settings = MapperSettings(h_gain=100.0, v_gain=100.0, invert_x=False, max_step=400.0)

    slow = RelativeMapper(settings)
    slow.update((0.0, 100.0))
    slow_total = sum(slow.update((i + 1.0, 100.0))[0] for i in range(30))

    fast = RelativeMapper(settings)
    fast.update((0.0, 100.0))
    fast_total = fast.update((10.0, 100.0))[0]
    fast_total += travel(fast, (10.0, 100.0), 10)  # let the carry drain

    assert slow_total == pytest.approx(3000.0, abs=1.0)
    assert fast_total == pytest.approx(1000.0, abs=1.0)


def test_carry_is_bounded_so_a_glitch_is_still_truncated():
    settings = MapperSettings(h_gain=100.0, v_gain=100.0, invert_x=False, max_step=400.0)
    mapper = RelativeMapper(settings)
    mapper.update((0.0, 100.0))
    mapper.update((1000.0, 100.0))  # absurd jump: 100,000px demanded

    drained = travel(mapper, (1000.0, 100.0), 50)

    # One step plus the bounded carry, not the whole 100,000px paid out slowly.
    assert drained <= 400.0 * CARRY_FRAMES + 1.0


def test_step_is_clamped_without_distorting_direction():
    settings = MapperSettings(h_gain=100.0, v_gain=100.0, invert_x=False, max_step=50.0)
    mapper = RelativeMapper(settings)
    mapper.update((100.0, 100.0))

    dx, dy = mapper.update((110.0, 110.0))

    assert math.hypot(dx, dy) == pytest.approx(50.0)
    assert dx == pytest.approx(dy)  # the 45-degree direction survives the clamp


def test_absolute_maps_frame_corners_onto_the_target_screen():
    mapper = AbsoluteMapper(frame_size=(640, 480), target=PRIMARY, invert_x=False)

    assert mapper.update((0.0, 0.0)) == (0.0, 0.0)
    assert mapper.update((639.0, 479.0)) == (2559.0, 1439.0)


def test_absolute_inverts_x_by_default():
    mapper = AbsoluteMapper(frame_size=(640, 480), target=PRIMARY)

    x, _ = mapper.update((0.0, 0.0))

    assert x == pytest.approx(2559.0)


def test_absolute_targets_one_screen_not_the_whole_desktop():
    # Mapping onto the bounding box would aim at coordinates on no monitor.
    right_screen = ScreenBounds(left=2560, top=0, width=2560, height=1440)
    mapper = AbsoluteMapper(frame_size=(640, 480), target=right_screen, invert_x=False)

    x, y = mapper.update((320.0, 240.0))

    assert 2560 <= x < 5120
    assert 0 <= y < 1440


def test_absolute_reports_nothing_when_the_marker_is_lost():
    mapper = AbsoluteMapper(frame_size=(640, 480), target=PRIMARY)

    assert mapper.update(None) is None

"""Cursor control tests. These use the recording backend so CI can run them
on Linux without a display or a real pointer."""

import pytest

from accesscam.mouse import ABSOLUTE_RANGE, CursorController, ScreenBounds, to_absolute
from accesscam.mouse.fake import RecordingMouse

# The development machine: monitors above and to the left of the primary one,
# so the desktop origin is negative.
NEGATIVE_ORIGIN = ScreenBounds(left=-2560, top=-2160, width=7680, height=3600)


def test_absolute_maps_origin_and_far_corner():
    bounds = ScreenBounds(left=0, top=0, width=1920, height=1080)

    assert to_absolute(0, 0, bounds) == (0, 0)
    assert to_absolute(1919, 1079, bounds) == (ABSOLUTE_RANGE, ABSOLUTE_RANGE)


def test_absolute_handles_negative_origin():
    # The top-left of this desktop is (-2560, -2160), not (0, 0). Mapping it to
    # 0 is the whole point of subtracting the origin first.
    assert to_absolute(-2560, -2160, NEGATIVE_ORIGIN) == (0, 0)

    centre_x = NEGATIVE_ORIGIN.left + NEGATIVE_ORIGIN.width // 2
    nx, _ = to_absolute(centre_x, 0, NEGATIVE_ORIGIN)
    assert nx == pytest.approx(ABSOLUTE_RANGE // 2, abs=10)


def test_sub_pixel_deltas_accumulate_instead_of_vanishing():
    # The regression this guards: rounding each delta independently, or reading
    # the integer OS position back every frame, would discard all ten of these
    # and the cursor would never move at slow speeds.
    mouse = RecordingMouse(bounds=NEGATIVE_ORIGIN, start=(0, 0))
    cursor = CursorController(mouse)

    for _ in range(10):
        cursor.move_by(0.3, 0.0)

    assert cursor.position[0] == pytest.approx(3.0)
    assert mouse.position()[0] == 3


def test_no_event_is_sent_while_the_rounded_pixel_is_unchanged():
    mouse = RecordingMouse(bounds=NEGATIVE_ORIGIN, start=(0, 0))
    cursor = CursorController(mouse)

    for _ in range(4):
        cursor.move_by(0.1, 0.1)

    # 0.4px of accumulated motion does not round to a new pixel yet.
    assert mouse.moves == []

    cursor.move_by(0.2, 0.2)
    assert mouse.moves == [(1, 1)]


def test_position_is_clamped_to_the_desktop():
    mouse = RecordingMouse(bounds=NEGATIVE_ORIGIN, start=(0, 0))
    cursor = CursorController(mouse)

    cursor.move_by(-100_000, -100_000)
    assert cursor.position == (float(NEGATIVE_ORIGIN.left), float(NEGATIVE_ORIGIN.top))

    cursor.move_by(1_000_000, 1_000_000)
    assert cursor.position == (
        float(NEGATIVE_ORIGIN.right - 1),
        float(NEGATIVE_ORIGIN.bottom - 1),
    )


def test_clamping_does_not_bank_overshoot():
    # Pushing hard into an edge and then reversing should move away immediately,
    # not spend the overshoot first.
    mouse = RecordingMouse(bounds=NEGATIVE_ORIGIN, start=(0, 0))
    cursor = CursorController(mouse)

    cursor.move_by(-100_000, 0)
    cursor.move_by(5, 0)

    assert cursor.position[0] == pytest.approx(float(NEGATIVE_ORIGIN.left) + 5)


def test_sync_adopts_the_os_cursor_position():
    mouse = RecordingMouse(bounds=NEGATIVE_ORIGIN, start=(0, 0))
    cursor = CursorController(mouse)

    mouse._position = (500, -300)
    cursor.sync()

    assert cursor.position == (500.0, -300.0)

    # After syncing, the next delta is applied from the adopted position.
    cursor.move_by(2.0, 0.0)
    assert mouse.moves == [(502, -300)]


def test_bounds_geometry():
    assert NEGATIVE_ORIGIN.right == 5120
    assert NEGATIVE_ORIGIN.bottom == 1440


def test_cursor_does_not_travel_into_regions_with_no_monitor():
    # The reported bug. The top display spans x 0-3840 and the right display
    # x 2560-5120, so above x 3840 there is no screen. Pushing up from the
    # right display there used to let the internal position climb into that
    # empty rectangle while Windows pinned the visible cursor to the edge -
    # so moving back down spent the phantom travel before anything moved.
    mouse = RecordingMouse(start=(4500, 700))
    cursor = CursorController(mouse)

    for _ in range(60):
        cursor.move_by(0.0, -30.0)  # 1800px of upward movement

    assert cursor.position[1] == 0.0  # pinned at the top edge, not above it

    # One frame of downward movement must move the cursor immediately.
    before = mouse.position()
    cursor.move_by(0.0, 12.0)

    assert mouse.position()[1] > before[1]


def test_transition_to_another_monitor_still_works():
    # Directly under the top display, moving up must cross onto it.
    mouse = RecordingMouse(start=(1500, 30))
    cursor = CursorController(mouse)

    cursor.move_by(0.0, -100.0)

    assert cursor.position[1] < 0.0


def test_blocked_axis_still_slides_along_the_edge():
    # Pressed against the top edge where there is no screen above, horizontal
    # movement must still work rather than sticking.
    mouse = RecordingMouse(start=(4500, 0))
    cursor = CursorController(mouse)

    cursor.move_by(-40.0, -40.0)

    assert cursor.position[0] == 4460.0
    assert cursor.position[1] == 0.0


def test_single_monitor_backends_are_unaffected():
    single = ScreenBounds(left=0, top=0, width=1920, height=1080)
    mouse = RecordingMouse(bounds=single, start=(100, 100))
    cursor = CursorController(mouse)

    cursor.move_by(-1000.0, -1000.0)

    assert cursor.position == (0.0, 0.0)

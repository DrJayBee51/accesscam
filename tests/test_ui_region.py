"""Region-of-interest editing, driven through real mouse and key events.

None of this is reachable from the pure-logic tests: the region is set by
dragging handles on a widget, so the thing worth testing is the widget, not the
arithmetic underneath it.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

pytestmark = pytest.mark.usefixtures("qt_app")


def corners(window) -> list[QPoint]:
    """The region's four corner handles, in preview coordinates.

    Never returns a null QPoint. `QPoint(0, 0)` is null, and QTest quietly aims
    at the widget centre when handed one - which turns a corner-handle test into
    a move-the-box test that passes for the wrong reason.
    """
    return [QPoint(max(int(p.x()), 1), max(int(p.y()), 1)) for p in window.preview._corners()]


def drag(window, start: QPoint, end: QPoint) -> None:
    preview = window.preview
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(preview, end)
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)


def test_the_region_starts_as_the_whole_frame(window):
    assert window.config.roi() == (0, 0, 640, 480)
    assert window.config.roi_is_whole_frame()


def test_a_corner_resizes_against_its_opposite(window):
    before = window.config.roi()
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 40, bottom_right.y() - 30))

    after = window.config.roi()
    assert after[2] < before[2]
    assert after[3] < before[3]
    assert after[:2] == before[:2]  # the opposite corner is the anchor


def test_dragging_inside_moves_without_resizing(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 40, bottom_right.y() - 30))

    before = window.config.roi()
    box = window.preview._box_rect()
    centre = QPoint(int(box.center().x()), int(box.center().y()))
    drag(window, centre, QPoint(centre.x() + 12, centre.y() + 9))

    after = window.config.roi()
    assert after[:2] != before[:2]
    assert after[2:] == before[2:]


def test_a_press_outside_the_box_does_nothing(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 60, bottom_right.y() - 45))
    before = window.config.roi()

    # Well outside the box, and a long drag rather than a slip: neither draws a
    # new region. Losing a tuned one to a stray click costs more than redrawing
    # saves, and the handles already cover it.
    outside = QPoint(window.preview.width() - 4, window.preview.height() - 4)
    drag(window, outside, QPoint(outside.x() - 120, outside.y() - 90))

    assert window.config.roi() == before


def test_a_corner_cannot_collapse_the_region(window):
    # Dragged past its opposite, a corner must stop rather than invert or leave
    # a box too small to hold the marker - which would stop tracking dead.
    from accesscam.ui.preview import MIN_REGION_PX

    bottom_right = corners(window)[3]
    top_left = corners(window)[0]
    drag(window, bottom_right, QPoint(top_left.x() - 60, top_left.y() - 60))

    _, _, w, h = window.config.roi()
    assert w >= MIN_REGION_PX
    assert h >= MIN_REGION_PX


def test_arrow_keys_move_the_region(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 40, bottom_right.y() - 30))

    before = window.config.roi()
    window.preview.setFocus()
    QTest.keyClick(window.preview, Qt.Key.Key_Right)

    after = window.config.roi()
    assert after[0] > before[0]
    assert after[2:] == before[2:]  # moving never resizes


def test_shift_arrow_resizes_the_region(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 40, bottom_right.y() - 30))

    before = window.config.roi()
    window.preview.setFocus()
    QTest.keyClick(window.preview, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)

    after = window.config.roi()
    assert after[3] > before[3]
    assert after[:2] == before[:2]


def test_the_region_never_leaves_the_frame(window):
    top_left = corners(window)[0]
    drag(window, top_left, QPoint(window.preview.width() + 200, window.preview.height() + 200))

    x, y, w, h = window.config.roi()
    assert x >= 0
    assert y >= 0
    assert x + w <= 640
    assert y + h <= 480


def test_the_engine_follows_every_edit(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 50, bottom_right.y() - 40))

    assert window.engine.tracker.roi == window.config.roi()


def test_reset_restores_the_whole_frame(window):
    bottom_right = corners(window)[3]
    drag(window, bottom_right, QPoint(bottom_right.x() - 50, bottom_right.y() - 40))
    assert not window.config.roi_is_whole_frame()

    window._reset_roi()

    assert window.config.roi() == (0, 0, 640, 480)
    assert window.engine.tracker.roi == (0, 0, 640, 480)

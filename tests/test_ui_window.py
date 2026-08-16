"""Window behaviour: focus, layout stability and live retuning.

These guard things that are invisible until they break, and then look like a
different bug entirely - a card that shrinks the first time a message appears,
or a button left lit long after it was pressed.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QPushButton, QSlider

from accesscam.ui.help import HelpButton

pytestmark = pytest.mark.usefixtures("qt_app")


def geometry(window) -> dict:
    return {
        "window": (window.width(), window.height()),
        "preview card": window._preview_card.height(),
        "camera controls": window._camera_controls.height(),
        "curve card": window._curve_card.height(),
        "movement controls": window._movement_controls.height(),
    }


# -- layout ---------------------------------------------------------------


def test_both_tabs_have_matching_card_heights(window):
    shape = geometry(window)
    assert shape["preview card"] == shape["curve card"]
    assert shape["camera controls"] == shape["movement controls"]


def test_the_columns_are_the_same_width_on_both_tabs(window):
    assert window._preview_card.width() == window._curve_card.width()
    assert window._camera_controls.width() == window._movement_controls.width()


def test_the_window_is_a_fixed_size(window):
    assert window.minimumSize() == window.maximumSize()


def test_a_status_message_does_not_resize_the_cards(window):
    # QMainWindow builds its status bar on demand, so the first message used to
    # create it after the size was fixed - and the height came out of the cards.
    before = geometry(window)

    window._reset_roi()
    assert "whole frame" in window.statusBar().currentMessage()
    assert geometry(window) == before

    window._revert()
    assert geometry(window) == before


def test_switching_tabs_does_not_move_anything(window):
    before = geometry(window)
    for index in (1, 0, 1, 0):
        window.tabs.setCurrentIndex(index)
    assert geometry(window) == before


# -- focus ----------------------------------------------------------------


def test_buttons_take_focus_from_tab_but_not_from_a_click(window):
    buttons = window.findChildren(QAbstractButton)
    assert buttons
    assert all(b.focusPolicy() == Qt.FocusPolicy.TabFocus for b in buttons)


def test_sliders_still_take_focus_from_a_click(window):
    # Clicking a slider to focus it is how the arrow keys then drive it, and
    # there the lit handle is telling the truth about which one they will move.
    sliders = window.findChildren(QSlider)
    assert sliders
    assert all(s.focusPolicy() != Qt.FocusPolicy.TabFocus for s in sliders)


@pytest.mark.parametrize("kind", ["stepButton", "help", "footer", "state"])
def test_a_clicked_button_is_not_left_focused(window, kind):
    buttons = window.findChildren(QAbstractButton)
    if kind == "stepButton":
        button = next(b for b in buttons if b.objectName() == "stepButton")
    elif kind == "help":
        button = next(b for b in buttons if isinstance(b, HelpButton))
    elif kind == "footer":
        button = next(
            b for b in buttons if isinstance(b, QPushButton) and b.text() == "Revert to saved"
        )
    else:
        button = window.state_button

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert not button.hasFocus()

    for popup in window.window().findChildren(object):
        closer = getattr(popup, "close", None)
        if callable(closer) and getattr(popup, "objectName", lambda: "")() == "helpPopup":
            closer()


# -- live retuning --------------------------------------------------------


def test_a_step_button_reaches_the_engine(window):
    tuner = next(t for t in window._tuners if t.key == "h_gain")
    before = window.engine.mapper.settings.h_gain

    tuner.step(+1)

    assert window.config.h_gain != before
    assert window.engine.mapper.settings.h_gain == window.config.h_gain


def test_the_state_button_toggles_the_pause(window):
    assert window.engine.pause.paused

    QTest.mouseClick(window.state_button, Qt.MouseButton.LeftButton)

    assert not window.engine.pause.paused


def test_the_state_button_reports_the_state_it_is_in(window):
    window._refresh()
    assert "PAUSED" in window.state_button.text()

    window.engine.pause.resume()
    window._refresh()
    assert "ACTIVE" in window.state_button.text()


def test_the_curve_is_drawn_from_the_configured_values(window):
    tuner = next(t for t in window._tuners if t.key == "accel_floor")
    tuner.set_value(0.4, emit=True)

    assert window.curve._floor == pytest.approx(window.config.accel_floor)
    assert window.curve._knee == pytest.approx(window.config.accel_knee)

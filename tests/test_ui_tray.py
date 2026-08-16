"""Tray icon behaviour, and the window's refusal to quit when closed."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from accesscam.ui.tray import ACTIVE, PAUSED, Tray, marker_icon

pytestmark = pytest.mark.usefixtures("qt_app")


def build_tray(window, **overrides):
    calls = {"paused": 0, "quit": 0, "minimised": []}
    tray = Tray(
        window=window,
        on_toggle_pause=lambda: calls.__setitem__("paused", calls["paused"] + 1),
        on_quit=lambda: calls.__setitem__("quit", calls["quit"] + 1),
        on_start_minimised=lambda checked: calls["minimised"].append(checked),
        start_minimised=overrides.get("start_minimised", False),
        parent=window,
    )
    return tray, calls


# -- the icon -------------------------------------------------------------


def test_the_icon_is_drawn_not_loaded():
    # Shipping no image asset is deliberate: the glyph has to change colour
    # with the state, which is the entire reason for a tray icon here.
    icon = marker_icon(ACTIVE)
    assert not icon.isNull()
    assert icon.availableSizes()


def test_the_glyph_draws_at_any_size():
    # The application icon is the same drawing at 16px and 256px. Every
    # dimension is a fraction of the canvas so neither has to be resampled -
    # a 2px ring survives no resampler.
    from accesscam.ui.tray import marker_pixmap

    for size in (16, 64, 256):
        pixmap = marker_pixmap(ACTIVE, size)
        assert pixmap.size().width() == size
        centre = pixmap.toImage().pixel(size // 2, size // 2)
        assert QColor(centre) == ACTIVE


def test_the_icon_colour_follows_the_pause_state(window):
    tray, _ = build_tray(window)

    tray.set_paused(True)
    parked = tray.icon().pixmap(64, 64).toImage()
    tray.set_paused(False)
    driving = tray.icon().pixmap(64, 64).toImage()

    centre = (32, 32)
    assert QColor(parked.pixel(*centre)) == PAUSED
    assert QColor(driving.pixel(*centre)) == ACTIVE


def test_the_tooltip_says_which_state_it_is_in(window):
    tray, _ = build_tray(window)

    tray.set_paused(True)
    assert "parked" in tray.toolTip()

    tray.set_paused(False)
    assert "driving" in tray.toolTip()


def test_the_menu_action_names_the_action_not_the_state(window):
    # "Take control" while parked, not "Parked" - a menu item is a verb.
    tray, _ = build_tray(window)

    tray.set_paused(True)
    assert tray.pause_action.text().startswith("Take control")

    tray.set_paused(False)
    assert tray.pause_action.text().startswith("Park")


# -- the menu -------------------------------------------------------------


def test_the_pause_item_toggles(window):
    tray, calls = build_tray(window)
    tray.pause_action.trigger()
    assert calls["paused"] == 1


def test_start_minimised_reports_both_ways(window):
    tray, calls = build_tray(window)

    tray.minimised_action.setChecked(True)
    tray.minimised_action.setChecked(False)

    assert calls["minimised"] == [True, False]


def test_start_minimised_opens_at_the_saved_setting(window):
    tray, _ = build_tray(window, start_minimised=True)
    assert tray.minimised_action.isChecked()


def test_settings_reveals_a_hidden_window(window):
    tray, _ = build_tray(window)
    window.hide()
    assert not window.isVisible()

    tray.settings_action.trigger()

    assert window.isVisible()


# -- closing --------------------------------------------------------------


def test_closing_hides_to_the_tray_rather_than_quitting(window):
    # Ending cursor control from a stray click on a title bar is a far worse
    # outcome, for someone using this as their mouse, than a hidden window.
    window.hides_to_tray = True
    window.show()

    assert not window.close()  # refused
    assert not window.isVisible()
    assert window.timer.isActive()  # still tracking behind the tray


def test_closing_really_closes_when_quit_was_asked_for(window):
    window.hides_to_tray = True
    window.quit_requested = True

    assert window.close()
    assert not window.timer.isActive()


def test_without_a_tray_closing_closes(window):
    # No tray means nowhere to hide, so the old behaviour has to stand or the
    # window becomes impossible to get rid of.
    window.hides_to_tray = False

    assert window.close()
    assert not window.timer.isActive()

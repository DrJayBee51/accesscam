"""Hotkey parsing and pause-state tests. No OS calls, so these run in CI."""

import pytest

from accesscam.hotkeys import DEFAULT_HOTKEY, PauseController, parse_hotkey
from accesscam.hotkeys.base import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
)


def test_parses_modifiers_and_key():
    hotkey = parse_hotkey("ctrl+alt+p")

    assert hotkey.modifiers == MOD_CONTROL | MOD_ALT
    assert hotkey.key_code == ord("P")


def test_parsing_is_case_and_space_insensitive():
    assert parse_hotkey("Ctrl + Alt + P") == parse_hotkey("ctrl+alt+p")


def test_modifier_aliases():
    assert parse_hotkey("control+shift+a").modifiers == MOD_CONTROL | MOD_SHIFT
    assert parse_hotkey("super+a").modifiers == MOD_WIN
    assert parse_hotkey("win+a").modifiers == MOD_WIN


def test_function_keys():
    assert parse_hotkey("shift+f8").key_code == 0x77
    assert parse_hotkey("ctrl+f1").key_code == 0x70
    assert parse_hotkey("ctrl+f24").key_code == 0x87


def test_named_keys():
    assert parse_hotkey("ctrl+space").key_code == 0x20
    assert parse_hotkey("alt+escape").key_code == 0x1B


def test_registration_sets_norepeat():
    # Holding the combination must not toggle the pause state repeatedly.
    modifiers, key = parse_hotkey("ctrl+alt+p").registration()

    assert modifiers & MOD_NOREPEAT
    assert key == ord("P")


def test_bare_function_key_is_allowed():
    # The fallback input is a mouth-operated QuadStick that cannot readily
    # produce modifier combinations, so the pause control must be reachable as
    # a single key.
    hotkey = parse_hotkey("f9")

    assert hotkey.modifiers == 0
    assert hotkey.key_code == 0x78


def test_bare_alphanumeric_key_is_rejected():
    # A global hotkey swallows the key system-wide; claiming 'p' would remove
    # it from all typing.
    with pytest.raises(ValueError):
        parse_hotkey("p")
    with pytest.raises(ValueError):
        parse_hotkey("5")


def test_bare_named_key_is_rejected():
    with pytest.raises(ValueError):
        parse_hotkey("space")


def test_unknown_modifier_and_key_are_rejected():
    with pytest.raises(ValueError):
        parse_hotkey("hyper+p")
    with pytest.raises(ValueError):
        parse_hotkey("ctrl+nonsense")


def test_default_hotkey_is_a_bare_function_key():
    hotkey = parse_hotkey(DEFAULT_HOTKEY)

    assert hotkey.modifiers == 0
    assert hotkey.key_code == 0x78  # F9


def test_starts_paused():
    # The pipeline drives the mouse with no window to click on, so it must
    # never start moving the cursor the moment it launches.
    assert PauseController().paused is True
    assert PauseController().active is False


def test_toggle_flips_and_reports_state():
    pause = PauseController()

    assert pause.toggle() is False
    assert pause.active is True
    assert pause.toggle() is True
    assert pause.active is False


def test_listeners_are_notified_on_change():
    pause = PauseController()
    seen = []
    pause.on_change(seen.append)

    pause.resume()
    pause.pause()

    assert seen == [False, True]


def test_no_notification_when_state_is_unchanged():
    pause = PauseController()
    seen = []
    pause.on_change(seen.append)

    pause.pause()  # already paused

    assert seen == []

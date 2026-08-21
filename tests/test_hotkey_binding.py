"""Changing the pause hotkey while AccessCam runs.

The property that matters is not that rebinding works - it is what happens when
it does not. The pause hotkey is the only way to park the cursor from the
keyboard, and for someone whose pointer *is* AccessCam, a dropdown change that
silently leaves no working hotkey is worse than one that refuses.
"""

from __future__ import annotations

import pytest

from accesscam.hotkeys import binding as binding_module
from accesscam.hotkeys.binding import HotkeyBinding


class FakeListener:
    """Stands in for the real registration, refusing keys on demand."""

    refuse: set[str] = set()
    live: list[str] = []

    def __init__(self, hotkey, on_trigger):
        self.hotkey = hotkey
        self.started = False

    def start(self, timeout: float = 2.0):
        if self.hotkey.label in FakeListener.refuse:
            raise RuntimeError(f"{self.hotkey.label} is held by another application")
        self.started = True
        FakeListener.live.append(self.hotkey.label)

    def stop(self):
        self.started = False
        if self.hotkey.label in FakeListener.live:
            FakeListener.live.remove(self.hotkey.label)


@pytest.fixture(autouse=True)
def fake_listeners(monkeypatch):
    FakeListener.refuse = set()
    FakeListener.live = []
    monkeypatch.setattr(binding_module, "create_listener", FakeListener)
    return FakeListener


def test_binding_registers_the_key():
    b = HotkeyBinding(lambda: None)

    assert b.bind("f9").ok
    assert b.label == "f9"
    assert FakeListener.live == ["f9"]


def test_changing_the_key_releases_the_old_one():
    # Two live registrations would mean the old key still swallowed globally.
    b = HotkeyBinding(lambda: None)
    b.bind("f9")

    assert b.bind("f8").ok
    assert FakeListener.live == ["f8"]
    assert b.label == "f8"


def test_rebinding_the_same_key_works():
    # Reselecting what is already chosen must not fail against our own
    # registration, which is what happens if the old one is not released first.
    b = HotkeyBinding(lambda: None)
    b.bind("f9")

    assert b.bind("f9").ok
    assert FakeListener.live == ["f9"]


def test_a_key_another_program_holds_falls_back_to_the_previous_one(fake_listeners):
    b = HotkeyBinding(lambda: None)
    b.bind("f9")
    fake_listeners.refuse = {"f8"}

    result = b.bind("f8")

    assert not result.ok
    assert b.label == "f9", "must not be left with the key that failed"
    assert FakeListener.live == ["f9"], "the working hotkey must still be registered"
    assert "F8" in result.message and "F9" in result.message


def test_an_invalid_key_is_refused_without_touching_the_working_one():
    b = HotkeyBinding(lambda: None)
    b.bind("f9")

    result = b.bind("p")  # a bare letter would be swallowed system-wide

    assert not result.ok
    assert b.label == "f9"
    assert FakeListener.live == ["f9"]


def test_it_says_so_when_nothing_could_be_registered(fake_listeners):
    # The worst case, and the one the message has to be honest about: no
    # hotkey at all means the cursor cannot be parked from the keyboard.
    fake_listeners.refuse = {"f9"}
    b = HotkeyBinding(lambda: None)

    result = b.bind("f9")

    assert not result.ok
    assert b.label is None
    assert "cannot be parked" in result.message


def test_stopping_releases_the_registration():
    b = HotkeyBinding(lambda: None)
    b.bind("f9")

    b.stop()

    assert FakeListener.live == []

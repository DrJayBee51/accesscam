"""Recovering when the camera goes away and comes back.

The reported failure: AccessCam left running, camera unplugged, plugged back in
on return - and the preview stayed black. The capture loop could not tell a
dead camera from a dropped frame, so it span on a dead handle forever and
nothing ever reopened it. Unplugging is a daily event here, not an edge case.
"""

from __future__ import annotations

import numpy as np
import pytest

from accesscam import engine as engine_module
from accesscam.camera import CameraError
from accesscam.config import Config
from accesscam.engine import Engine
from accesscam.mouse import CursorController
from accesscam.mouse.base import ScreenBounds
from accesscam.mouse.fake import RecordingMouse


class DeadCamera:
    """A camera that has stopped delivering, as an unplugged one does."""

    def __init__(self, device=1):
        from accesscam.camera import CameraSettings

        self.settings = CameraSettings(device=device)
        self.exposure = -9
        self.measured_fps = 0.0
        self.closed = False

    def read(self):
        return None

    def close(self, restore_auto_exposure: bool = False):
        self.closed = True


class LiveCamera:
    """A camera that works, standing in for the reconnected one."""

    def __init__(self, device=1):
        from accesscam.camera import CameraSettings

        self.settings = CameraSettings(device=device)
        self.exposure = -9
        self.measured_fps = 29.4
        self.opened = False
        self.closed = False

    def open(self, wait: float = 0.0):
        self.opened = True

    def set_exposure(self, value):
        self.exposure = value
        return value

    def read(self):
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def close(self, restore_auto_exposure: bool = False):
        self.closed = True


def build_engine(camera):
    cursor = CursorController(RecordingMouse(bounds=ScreenBounds(0, 0, 2560, 1440), start=(0, 0)))
    return Engine(Config(device=camera.settings.device), camera, cursor)


@pytest.fixture
def sources(monkeypatch):
    """Control what a reconnection attempt finds at each device index."""
    made: list = []

    def install(available: dict):
        def factory(settings):
            cam = (
                LiveCamera(settings.device)
                if settings.device in available
                else _Absent(settings.device)
            )
            made.append(cam)
            return cam

        monkeypatch.setattr(engine_module, "CameraSource", factory)
        return made

    return install


class _Absent(LiveCamera):
    """An index with nothing on it."""

    def open(self, wait: float = 0.0):
        raise CameraError(f"Could not open camera device {self.settings.device}.")


def test_a_dead_camera_is_reopened_on_its_own_index(sources):
    sources({1: True})
    engine = build_engine(DeadCamera(device=1))

    assert engine._reconnect() is True
    assert isinstance(engine.camera, LiveCamera)
    assert engine.camera.settings.device == 1
    assert engine.camera.opened


def test_the_dead_handle_is_released_before_reopening(sources):
    # Reopening while still holding the old handle contends with it.
    sources({1: True})
    dead = DeadCamera(device=1)
    engine = build_engine(dead)

    engine._reconnect()

    assert dead.closed


def test_it_finds_the_camera_on_a_different_index(sources):
    # USB does not promise the same number twice. A camera back as device 2
    # while the config says 1 is the case a naive reopen fails at, looking
    # exactly like a hardware fault.
    sources({2: True})
    engine = build_engine(DeadCamera(device=1))

    assert engine._reconnect() is True
    assert engine.camera.settings.device == 2


def test_the_configured_index_is_tried_first(sources):
    made = sources({1: True, 2: True})
    engine = build_engine(DeadCamera(device=1))

    engine._reconnect()

    assert made[0].settings.device == 1
    assert engine.camera.settings.device == 1


def test_nothing_connected_means_no_reconnection(sources):
    sources({})
    engine = build_engine(DeadCamera(device=1))

    assert engine._reconnect() is False


def test_the_exposure_is_carried_across(sources):
    # A reconnected camera at the default exposure would be useless for
    # tracking - the marker only stands out at a short one.
    sources({1: True})
    dead = DeadCamera(device=1)
    dead.exposure = -11
    engine = build_engine(dead)

    engine._reconnect()

    assert engine.camera.exposure == -11


def test_reconnecting_clears_the_stale_marker_position(sources):
    # The old position describes a frame from before the disconnection. Carried
    # over, it delivers one enormous displacement the instant the camera
    # returns, throwing the cursor across the desktop.
    sources({1: True})
    engine = build_engine(DeadCamera(device=1))
    engine.step(np.full((480, 640, 3), 255, dtype=np.uint8))

    engine._reconnect()

    assert engine.status().position is None
    assert engine.latest_frame() is None


def test_a_camera_that_opens_but_stays_silent_is_not_a_reconnection(monkeypatch):
    # A device part-way through re-enumerating can hand back a handle that
    # never delivers. Accepting it would end the retry loop on a dead camera.
    class Silent(LiveCamera):
        def read(self):
            return None

    monkeypatch.setattr(engine_module, "CameraSource", lambda settings: Silent(settings.device))
    engine = build_engine(DeadCamera(device=1))

    assert engine._reconnect() is False


# -- the loop's own judgement ----------------------------------------------


def test_a_single_dropped_frame_does_not_trigger_a_reconnect(sources, monkeypatch):
    """The distinction the old loop could not make.

    Drivers drop the occasional frame; that is normal and must not tear the
    camera down. Only a sustained silence means the device is gone.
    """
    sources({1: True})

    class Flaky(DeadCamera):
        def __init__(self):
            super().__init__(device=1)
            self.calls = 0

        def read(self):
            self.calls += 1
            return None if self.calls == 1 else np.zeros((480, 640, 3), dtype=np.uint8)

    engine = build_engine(Flaky())
    reconnects = []
    monkeypatch.setattr(engine, "_reconnect", lambda: reconnects.append(1) or True)

    engine.start()
    try:
        _wait_for(lambda: engine.status().frames > 3)
    finally:
        engine.stop()

    assert reconnects == []


def test_the_loop_reconnects_a_camera_that_stays_silent(sources, monkeypatch):
    sources({1: True})
    monkeypatch.setattr(engine_module, "RECONNECT_AFTER", 0.05)
    monkeypatch.setattr(engine_module, "RECONNECT_INTERVAL", 0.01)

    engine = build_engine(DeadCamera(device=1))
    engine.start()
    try:
        recovered = _wait_for(lambda: isinstance(engine.camera, LiveCamera), timeout=5.0)
    finally:
        engine.stop()

    assert recovered, "the loop never reconnected a permanently silent camera"


def _wait_for(condition, timeout: float = 5.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False

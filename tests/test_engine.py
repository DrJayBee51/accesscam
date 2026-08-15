"""Engine tests. A fake camera stands in for hardware, so these run anywhere."""

import threading
import time

import numpy as np
import pytest

from accesscam.config import Config
from accesscam.engine import Engine
from accesscam.hotkeys import PauseController
from accesscam.mouse import CursorController
from accesscam.mouse.base import ScreenBounds
from accesscam.mouse.fake import RecordingMouse

BOUNDS = ScreenBounds(left=0, top=0, width=2560, height=1440)


def frame_with_dot(x, y, radius=5, brightness=255):
    """A BGR frame with one bright disc, as the camera would deliver it."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ys, xs = np.ogrid[:480, :640]
    inside = (xs - x) ** 2 + (ys - y) ** 2 <= radius**2
    frame[inside] = brightness
    return frame


class FakeCamera:
    """Serves a scripted list of frames, then None for ever after."""

    def __init__(self, frames=(), fps=30.0):
        self._frames = list(frames)
        self._served = 0
        self.measured_fps = fps
        self.exposure = -9
        self.exposures_set = []
        self.closed = False

    def read(self):
        if self._served >= len(self._frames):
            return None
        frame = self._frames[self._served]
        self._served += 1
        return frame

    def set_exposure(self, value):
        self.exposure = value
        self.exposures_set.append(value)
        return value

    def close(self):
        self.closed = True


def build(config=None, frames=(), pause=None):
    engine = Engine(
        config or Config(),
        FakeCamera(frames),
        CursorController(RecordingMouse(bounds=BOUNDS, start=(1000, 700))),
        pause=pause,
    )
    return engine


def test_starts_paused_so_the_cursor_is_not_grabbed():
    engine = build(frames=[frame_with_dot(300, 240)])

    assert engine.status().paused
    engine.step(frame_with_dot(300, 240))
    engine.step(frame_with_dot(320, 240))

    assert engine.cursor.position == (1000, 700)


def test_resuming_moves_the_cursor():
    engine = build()
    engine.pause.resume()

    engine.step(frame_with_dot(300, 240))
    engine.step(frame_with_dot(320, 240))

    assert engine.cursor.position != (1000, 700)


def test_counts_frames_and_losses():
    engine = build()

    engine.step(frame_with_dot(300, 240))
    engine.step(np.zeros((480, 640, 3), dtype=np.uint8))  # nothing bright
    engine.step(frame_with_dot(305, 240))

    status = engine.status()
    assert status.frames == 3
    assert status.lost == 1
    assert status.lost_fraction == pytest.approx(1 / 3)


def test_status_reports_tracking_state_and_position():
    engine = build()
    engine.step(frame_with_dot(300, 240))

    status = engine.status()
    assert status.tracking
    assert status.position is not None
    assert status.position[0] == pytest.approx(300.0, abs=2.0)

    engine.step(np.zeros((480, 640, 3), dtype=np.uint8))
    assert not engine.status().tracking


def test_resuming_resets_the_mapper_so_no_delta_crosses_the_pause():
    # The marker moves while paused. Resuming must not deliver that movement
    # as one jump - the cursor would fly across the desktop.
    engine = build()
    engine.step(frame_with_dot(200, 240))
    engine.step(frame_with_dot(400, 240))

    before = engine.cursor.position
    engine.pause.resume()
    engine.step(frame_with_dot(400, 240))

    assert engine.cursor.position == before


def test_apply_retunes_without_restarting():
    engine = build()
    engine.apply(Config(h_gain=55.0, v_gain=66.0, min_cutoff=0.5, threshold=123))

    assert engine.mapper.settings.h_gain == 55.0
    assert engine.mapper.settings.v_gain == 66.0
    assert engine.tracker.threshold == 123


def test_apply_reaches_both_smoothing_axes():
    # The One Euro filters hold a reference to the same settings object as the
    # smoother. Replacing the object instead of mutating it would retune the
    # parent and leave both axes running on the old values.
    engine = build()
    engine.apply(Config(min_cutoff=0.9, beta=0.7))

    assert engine.smoother._x.settings.min_cutoff == 0.9
    assert engine.smoother._y.settings.beta == 0.7


def test_apply_sets_exposure_only_when_it_changed():
    engine = build()
    engine.camera.exposure = -9

    engine.apply(Config(exposure=-9))
    assert engine.camera.exposures_set == []

    engine.apply(Config(exposure=-7))
    assert engine.camera.exposures_set == [-7]


def test_apply_carries_the_region_of_interest():
    engine = build()
    assert engine.tracker.roi is None

    engine.apply(Config(roi_x=10, roi_y=20, roi_w=100, roi_h=80))
    assert engine.tracker.roi == (10, 20, 100, 80)


def test_latest_frame_is_a_copy():
    # Some capture backends reuse their buffer between reads, so handing out
    # the array itself would let the next frame redraw a widget mid-paint.
    engine = build()
    frame = frame_with_dot(300, 240)
    engine.step(frame)

    handed_out = engine.latest_frame()
    assert handed_out is not None
    assert handed_out is not frame
    assert np.array_equal(handed_out, frame)


def test_latest_frame_is_none_before_the_first_one():
    assert build().latest_frame() is None


def test_the_thread_runs_and_stops():
    frames = [frame_with_dot(300 + i, 240) for i in range(5)]
    engine = build(frames=frames)

    engine.start()
    deadline = time.monotonic() + 2.0
    while engine.status().frames < len(frames) and time.monotonic() < deadline:
        time.sleep(0.01)
    engine.stop()

    assert engine.status().frames == len(frames)
    assert not engine.running


def test_stop_is_safe_to_call_twice():
    engine = build()
    engine.start()
    engine.stop()
    engine.stop()

    assert not engine.running


def test_starting_twice_is_refused():
    engine = build()
    engine.start()
    try:
        with pytest.raises(RuntimeError):
            engine.start()
    finally:
        engine.stop()


def test_a_dead_camera_does_not_spin_the_thread():
    # read() returning None for ever must not become a busy loop on a core.
    engine = build(frames=[])
    engine.start()
    time.sleep(0.05)
    engine.stop()

    assert engine.status().frames == 0


def test_an_external_pause_controller_is_honoured():
    pause = PauseController()
    engine = build(pause=pause)

    assert engine.pause is pause
    pause.resume()
    assert not engine.status().paused


def test_status_is_a_snapshot_not_a_live_view():
    engine = build()
    engine.step(frame_with_dot(300, 240))
    first = engine.status()

    engine.step(frame_with_dot(305, 240))

    assert first.frames == 1
    assert engine.status().frames == 2


def test_status_can_be_read_while_the_thread_runs():
    frames = [frame_with_dot(300 + (i % 20), 240) for i in range(200)]
    engine = build(frames=frames)
    seen = []
    errors = []

    def reader():
        try:
            for _ in range(200):
                status = engine.status()
                seen.append(status.frames)
        except Exception as exc:  # noqa: BLE001 - the test is what it raises
            errors.append(exc)

    engine.start()
    watcher = threading.Thread(target=reader)
    watcher.start()
    watcher.join(5.0)
    engine.stop()

    assert not errors
    assert seen == sorted(seen)  # a snapshot never goes backwards

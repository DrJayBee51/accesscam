"""Standing aside when another device moves the cursor.

The case: someone picks up the real mouse to show you something. Two devices
driving one cursor fight, and the head tracker wins by sheer frame rate - which
makes the mouse feel broken rather than the tracker feel polite.
"""

from __future__ import annotations

import numpy as np
import pytest

from accesscam.config import Config
from accesscam.engine import Engine
from accesscam.mouse import CursorController
from accesscam.mouse.base import ScreenBounds
from accesscam.mouse.fake import RecordingMouse

BOUNDS = ScreenBounds(0, 0, 2560, 1440)


class Camera:
    measured_fps = 29.4
    exposure = -9

    def __init__(self, marker=(320, 240)):
        self.marker = marker

    def read(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        if self.marker:
            x, y = self.marker
            ys, xs = np.ogrid[:480, :640]
            frame[(xs - x) ** 2 + (ys - y) ** 2 <= 36] = 245
        return frame

    def set_exposure(self, value):
        return value

    def close(self, restore_auto_exposure: bool = False):
        pass


def build(**overrides):
    config = Config(**overrides)
    mouse = RecordingMouse(bounds=BOUNDS, start=(1000, 700))
    engine = Engine(config, Camera(), CursorController(mouse))
    engine.pause.resume()  # engines start parked
    return engine, mouse


def drive(engine, camera, frames=3):
    """Feed frames with the marker moving, so the mapper produces real deltas."""
    for i in range(frames):
        camera.marker = (320 + i * 6, 240)
        engine.step(camera.read())


def test_head_movement_drives_the_cursor_normally():
    engine, mouse = build()
    drive(engine, engine.camera)

    assert mouse.moves, "baseline: the cursor should move when nothing interferes"


def test_it_stands_aside_on_the_frame_the_other_device_moves():
    engine, mouse = build()
    drive(engine, engine.camera)

    # Somebody grabs the real mouse.
    mouse._position = (1800, 400)
    before = len(mouse.moves)
    drive(engine, engine.camera, frames=1)

    assert len(mouse.moves) == before, "AccessCam kept moving the cursor during foreign input"


def test_it_resumes_from_where_the_other_device_left_the_cursor():
    # Snapping back to where AccessCam thought the cursor was would undo the
    # move the other person just made, which is the fight in miniature.
    engine, mouse = build()
    drive(engine, engine.camera)

    mouse._position = (1800, 400)
    drive(engine, engine.camera, frames=1)  # yields, and adopts the new spot

    assert engine.cursor.position == (1800.0, 400.0)


def test_it_resumes_on_the_next_frame_with_no_delay():
    engine, mouse = build(yield_delay=0.0)
    drive(engine, engine.camera)

    mouse._position = (1800, 400)
    drive(engine, engine.camera, frames=1)  # the yielding frame

    before = len(mouse.moves)
    drive(engine, engine.camera, frames=3)  # nothing foreign since

    assert len(mouse.moves) > before, "should be driving again once the mouse stopped"


def test_a_delay_holds_off_after_the_other_device_stops(monkeypatch):
    engine, mouse = build(yield_delay=1.0)
    drive(engine, engine.camera)

    mouse._position = (1800, 400)
    drive(engine, engine.camera, frames=1)

    before = len(mouse.moves)
    drive(engine, engine.camera, frames=3)

    assert len(mouse.moves) == before, "the hold-off should still be running"


def test_the_delay_expires(monkeypatch):
    import accesscam.engine as engine_module

    engine, mouse = build(yield_delay=0.05)
    drive(engine, engine.camera)
    mouse._position = (1800, 400)
    drive(engine, engine.camera, frames=1)

    clock = [engine._yield_until + 1.0]
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock[0])

    before = len(mouse.moves)
    drive(engine, engine.camera, frames=3)

    assert len(mouse.moves) > before


def test_turning_it_off_lets_the_tracker_win():
    # The old behaviour, still available: some people would rather the head
    # tracker never yielded.
    engine, mouse = build(yield_to_mouse=False)
    drive(engine, engine.camera)

    mouse._position = (1800, 400)
    before = len(mouse.moves)
    drive(engine, engine.camera, frames=3)

    assert len(mouse.moves) > before


def test_accesscams_own_movement_never_counts_as_foreign():
    # The trap this design avoids: AccessCam moves the cursor constantly, so
    # any detection that cannot tell its own movement apart yields forever.
    engine, mouse = build()
    camera = engine.camera

    for i in range(20):
        camera.marker = (300 + i * 2, 240)
        engine.step(camera.read())

    # Asserting the property directly rather than counting moves: the cursor
    # eventually clamps against a screen edge and stops moving for reasons that
    # have nothing to do with yielding.
    assert engine._yield_until == 0.0, "AccessCam yielded to its own movement"
    assert mouse.moves, "and it should have been driving the whole time"


@pytest.mark.parametrize("jitter", [0, 1, 2])
def test_rounding_noise_does_not_trigger_a_yield(jitter):
    # Read-back can shift by a pixel through rounding or DPI scaling; a false
    # positive stutters tracking for no reason.
    engine, mouse = build()
    drive(engine, engine.camera)

    x, y = mouse._position
    mouse._position = (x + jitter, y)
    before = len(mouse.moves)
    drive(engine, engine.camera, frames=2)

    assert len(mouse.moves) > before, f"{jitter}px of noise should not count as foreign"

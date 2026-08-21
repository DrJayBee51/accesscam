"""The cursor-control pipeline, running independently of any front end.

Until now the pipeline lived inside `app.run` as a blocking loop that also did
the printing. That is fine for a terminal and impossible for a window: a Qt
event loop has to own the main thread, so the pipeline has to run beside it and
be *observed* rather than waited on.

This module is that pipeline with no opinion about who is watching. It owns the
camera, tracker, smoother, mapper and cursor, runs them on its own thread, and
publishes a status snapshot plus the latest frame. The terminal front end prints
those; the Qt one will draw them. Neither is privileged.

Two things are deliberately *not* here. The pause hotkey belongs to the front
end, because a window has a button and a terminal does not - the engine only
takes a `PauseController` and reacts to it. And nothing in here prints, because
a front end that cannot suppress output is not really a front end.
"""

from __future__ import annotations

import contextlib
import threading
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np

from accesscam.camera import CameraError, CameraSource
from accesscam.config import Config
from accesscam.hotkeys import PauseController
from accesscam.log import log
from accesscam.mapper import MapperSettings, RelativeMapper
from accesscam.mouse import CursorController
from accesscam.smoothing import PointSmoother, SmoothingSettings
from accesscam.tracker import DotTracker

# How long frames must stop arriving before the camera is treated as gone
# rather than merely dropping frames. Long enough to outlast a stall, short
# enough that replugging feels like it just works.
RECONNECT_AFTER = 2.0

# Gap between reconnection attempts. Opening an absent device costs the better
# part of a second under DirectShow, so this paces slow calls rather than
# spinning.
RECONNECT_INTERVAL = 1.0

# How far to look when the camera does not come back on its own index. Matches
# what `probe_devices` scans.
MAX_DEVICE_INDEX = 8


@dataclass(frozen=True)
class EngineStatus:
    """A consistent view of the pipeline, taken under the lock.

    Frozen and copied rather than handed out live: a front end reading six
    counters mid-frame would otherwise see three of them from one frame and
    three from the next, which is exactly the kind of bug that only appears
    under load and never reproduces.
    """

    frames: int = 0
    lost: int = 0
    fps: float = 0.0
    tracking: bool = False
    paused: bool = True
    position: tuple[float, float] | None = None
    peak_demand: float = 0.0
    clipped: int = 0
    steps: int = 0

    @property
    def lost_fraction(self) -> float:
        return self.lost / self.frames if self.frames else 0.0

    @property
    def clipped_fraction(self) -> float:
        return self.clipped / self.steps if self.steps else 0.0


class Engine:
    """Camera to tracker to smoother to mapper to cursor, on its own thread."""

    def __init__(
        self,
        config: Config,
        camera: CameraSource,
        cursor: CursorController,
        pause: PauseController | None = None,
    ) -> None:
        self.camera = camera
        self.cursor = cursor
        self.pause = pause or PauseController()

        self.tracker = DotTracker(
            threshold=config.threshold,
            min_area=config.min_area,
            max_area=config.max_area,
            max_jump=config.max_jump,
            min_circularity=config.min_circularity,
            roi=config.roi(),
        )
        self.smoother = PointSmoother(
            SmoothingSettings(
                min_cutoff=config.min_cutoff, beta=config.beta, d_cutoff=config.d_cutoff
            )
        )
        self.mapper = RelativeMapper(
            MapperSettings(
                h_gain=config.h_gain,
                v_gain=config.v_gain,
                invert_x=config.invert_x,
                invert_y=config.invert_y,
                dead_zone=config.dead_zone,
                max_step=config.max_step,
                accel_floor=config.accel_floor,
                accel_knee=config.accel_knee,
                accel_sharpness=config.accel_sharpness,
            )
        )

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._frames = 0
        self._lost = 0
        self._tracking = False
        self._position: tuple[float, float] | None = None
        self._frame: np.ndarray | None = None

        self.pause.on_change(self._on_pause_change)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Begin processing on a background thread."""
        if self._thread is not None:
            raise RuntimeError("Engine is already running.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="accesscam-engine")
        self._thread.daemon = True
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Ask the thread to finish and wait for it. Safe to call twice."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- observation -------------------------------------------------------

    def status(self) -> EngineStatus:
        """A snapshot of where the pipeline is, safe to read from any thread."""
        with self._lock:
            return EngineStatus(
                frames=self._frames,
                lost=self._lost,
                fps=self.camera.measured_fps,
                tracking=self._tracking,
                paused=self.pause.paused,
                position=self._position,
                peak_demand=self.mapper.peak_demand,
                clipped=self.mapper.clipped,
                steps=self.mapper.steps,
            )

    def latest_frame(self) -> np.ndarray | None:
        """A copy of the most recent frame, or None before the first one.

        Copied here rather than in the loop so a headless run pays nothing for
        a preview nobody is watching. Some capture backends reuse their buffer
        between reads, so handing out the array itself would let the next frame
        redraw a widget mid-paint.
        """
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def use_camera(self, camera: CameraSource) -> None:
        """Adopt a different camera. The engine must be stopped first.

        Not part of `apply`, and deliberately not doable while running: the
        capture has to be closed and reopened, and the loop cannot be reading
        from a camera that is being swapped underneath it.

        Everything downstream is reset, because a new camera means the previous
        marker position describes a frame that no longer exists - carrying it
        over would deliver one enormous displacement on the first frame.
        """
        if self.running:
            raise RuntimeError("Stop the engine before changing its camera.")
        self.camera = camera
        self.tracker.reset()
        self.smoother.reset()
        self.mapper.reset()
        with self._lock:
            self._frame = None
            self._position = None
            self._tracking = False

    # -- live tuning -------------------------------------------------------

    def apply(self, config: Config) -> None:
        """Adopt new settings without restarting.

        The settings dataclasses are mutated in place rather than replaced,
        because the One Euro filters hold references to the same
        `SmoothingSettings` object their `PointSmoother` does - swapping the
        object would retune the parent and leave both axes on the old values.

        Camera *identity* and frame geometry are not here: changing `device`,
        `width`, `height` or `fps` means closing and reopening the capture, so a
        front end that wants those does a restart. Exposure is live because it
        is the one camera setting that changes with the room.
        """
        with self._lock:
            self.tracker.threshold = config.threshold
            self.tracker.min_area = config.min_area
            self.tracker.max_area = config.max_area
            self.tracker.max_jump = config.max_jump
            self.tracker.min_circularity = config.min_circularity
            self.tracker.roi = config.roi()

            smoothing = self.smoother.settings
            smoothing.min_cutoff = config.min_cutoff
            smoothing.beta = config.beta
            smoothing.d_cutoff = config.d_cutoff

            mapping = self.mapper.settings
            mapping.h_gain = config.h_gain
            mapping.v_gain = config.v_gain
            mapping.invert_x = config.invert_x
            mapping.invert_y = config.invert_y
            mapping.dead_zone = config.dead_zone
            mapping.max_step = config.max_step
            mapping.accel_floor = config.accel_floor
            mapping.accel_knee = config.accel_knee
            mapping.accel_sharpness = config.accel_sharpness

            self.cursor.clutch = config.clutch

        if config.exposure != self.camera.exposure:
            self.camera.set_exposure(config.exposure)

    # -- internals ---------------------------------------------------------

    def _on_pause_change(self, paused: bool) -> None:
        """Re-adopt the real cursor position on resume.

        It may have been moved by other means while we were paused, and the
        mapper must not carry a stale position across the gap.
        """
        if not paused:
            self.cursor.sync()
            self.mapper.reset()

    def step(self, frame: np.ndarray) -> None:
        """Process one frame. Split out so tests can drive it without a thread."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        result = self.tracker.process(gray)
        position = result.position if result.found else None

        smoothed = self.smoother.update(position)

        if self.pause.active:
            self.cursor.move_by(*self.mapper.update(smoothed))
        else:
            # Keep the mapper from carrying a delta across the pause.
            self.mapper.reset()

        with self._lock:
            self._frames += 1
            if position is None:
                self._lost += 1
            self._tracking = result.found
            self._position = position
            self._frame = frame

    def _loop(self) -> None:
        starved_since: float | None = None
        next_attempt = 0.0

        while not self._stop.is_set():
            frame = self.camera.read()
            if frame is not None:
                starved_since = None
                self.step(frame)
                continue

            # A dropped frame is normal; a dead camera is not, and the two look
            # identical from here. Time tells them apart: a driver drops the odd
            # frame, it does not drop every frame for seconds on end.
            now = time.monotonic()
            if starved_since is None:
                starved_since = now
            elif now - starved_since >= RECONNECT_AFTER and now >= next_attempt:
                if self._reconnect():
                    starved_since = None
                else:
                    next_attempt = now + RECONNECT_INTERVAL

            # Yield rather than spinning a core while finding out which it is.
            time.sleep(0.001)

    def _reconnect(self) -> bool:
        """Try to reopen the camera after it stopped delivering frames.

        Unplugging is routine rather than exceptional - one camera moving
        between two machines - so this has to be automatic and quiet. Without
        it the loop spun on a dead handle forever: the preview froze black, and
        replugging the camera changed nothing because nothing ever reopened it.

        The device index is re-derived rather than trusted. USB does not promise
        the same number twice, and a camera that comes back as device 2 when the
        config says 1 is exactly the case a naive reopen fails at while looking
        like a hardware fault.
        """
        log.info("camera %s stopped delivering - reconnecting", self.camera.settings.device)

        # Let go of the dead handle first, or the reopen contends with it. No
        # exposure restoring here: this camera is not being abandoned, and the
        # driver would not hear it anyway.
        with contextlib.suppress(Exception):
            self.camera.close()

        for device in self._reconnect_candidates():
            candidate = CameraSource(replace(self.camera.settings, device=device))
            try:
                candidate.open()
                candidate.set_exposure(self.camera.exposure)
            except CameraError:
                continue

            if candidate.read() is None:
                # Opened but silent - a stale handle for a device that has not
                # finished re-enumerating. Not a reconnection.
                candidate.close()
                continue

            log.info("camera reconnected on device %s", device)
            self._adopt(candidate)
            return True

        return False

    def _reconnect_candidates(self):
        """The configured index first, then the others it may have moved to."""
        wanted = self.camera.settings.device
        return [wanted, *(d for d in range(MAX_DEVICE_INDEX) if d != wanted)]

    def _adopt(self, camera: CameraSource) -> None:
        """Swap in a reconnected camera from inside the running loop.

        `use_camera` refuses while running, and rightly - it exists for a user
        choosing a different camera, where the loop must not be reading through
        the swap. Here the loop *is* the caller and is between reads, so the
        same work is done directly.
        """
        self.camera = camera
        self.tracker.reset()
        self.smoother.reset()
        # The marker position described a frame from before the disconnection.
        # Carried over it would deliver one enormous displacement, throwing the
        # cursor across the desktop the instant the camera came back.
        self.mapper.reset()
        with self._lock:
            self._frame = None
            self._position = None
            self._tracking = False

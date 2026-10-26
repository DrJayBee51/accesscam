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
import csv
import threading
import time
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from accesscam.camera import CameraError, CameraSource
from accesscam.config import Config, config_dir
from accesscam.hotkeys import PauseController
from accesscam.log import log
from accesscam.mapper import MapperSettings, RelativeMapper
from accesscam.mouse import CursorController
from accesscam.smoothing import PointSmoother, SmoothingSettings
from accesscam.tracker import DotTracker, TrackResult

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

# How often a tracking summary goes in the log. Five minutes keeps a working
# day to about a hundred lines, so the rotating log still holds weeks of starts
# and stops, while a dropout too brief to see on screen still shows up in the
# counts.
STATS_EVERY = 300.0

# A recording is asked for by creating a file called `record` beside the
# config, and lasts this long. A file rather than a button because the question
# it answers - what was the tracker actually following just now - comes up
# while the window is closed and the cursor is in use.
RECORD_SECONDS = 30.0
RECORD_CHECK_EVERY = 1.0


def record_trigger() -> Path:
    return config_dir() / "record"


class _Recording:
    """Every frame for a short while: a CSV row each, and a video with the
    tracker's choice drawn on it, so a wrong pick can be seen and not inferred."""

    def __init__(self, folder: Path, roi: tuple[int, int, int, int] | None, now: float) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder
        self.started = now
        self.until = now + RECORD_SECONDS
        self._roi = roi
        self._file = open(folder / "frames.csv", "w", newline="")  # noqa: SIM115 - closed in close()
        self._csv = csv.writer(self._file)
        self._csv.writerow(["t", "found", "x", "y", "area", "brightness", "miss", "peak"])
        self._video: cv2.VideoWriter | None = None

    def add(self, frame: np.ndarray, result: TrackResult, peak: int, now: float) -> None:
        t = now - self.started
        if result.found:
            row = [f"{t:.3f}", 1, f"{result.x:.2f}", f"{result.y:.2f}"]
            row += [f"{result.area:.0f}", f"{result.brightness:.0f}", "", ""]
        else:
            row = [f"{t:.3f}", 0, "", "", "", "", result.miss, peak]
        self._csv.writerow(row)

        if self._video is None:
            height, width = frame.shape[:2]
            path = str(self.folder / "frames.avi")
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            self._video = cv2.VideoWriter(path, fourcc, 30.0, (width, height))
        shown = frame.copy()
        if self._roi is not None:
            x, y, w, h = self._roi
            cv2.rectangle(shown, (x, y), (x + w, y + h), (255, 160, 0), 1)
        if result.contour is not None:
            cv2.drawContours(shown, [result.contour], -1, (0, 255, 0), 1)
        label = f"{t:6.2f}s  " + (f"area {result.area:.0f}" if result.found else result.miss)
        cv2.putText(shown, label, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        self._video.write(shown)

    def close(self) -> None:
        self._file.close()
        if self._video is not None:
            self._video.release()


class _TrackingStats:
    """A window of frames, summarised into one log line.

    The point is a record to compare against: "spotty for a while" is a feeling,
    and a number per five minutes is something a month from now can be held up
    against. Why each lost frame was lost is the part that says what to change -
    "dark" with a peak just under the threshold is a dim marker, a peak far
    below it is no marker in view at all, and "outside roi" is a box that no
    longer fits where the user sits.
    """

    def __init__(self, now: float) -> None:
        self._run = 0
        self.reset(now)

    def reset(self, now: float) -> None:
        self.started = now
        self.frames = 0
        self.lost = 0
        self.dropouts = 0
        self.longest = 0
        self.misses: Counter[str] = Counter()
        self.dark_peak = 0
        self.area = 0.0
        self.brightness = 0.0

    def add(self, result: TrackResult, peak: int) -> None:
        self.frames += 1
        if result.found:
            self._run = 0
            self.area += result.area
            self.brightness += result.brightness
            return

        self.lost += 1
        self.misses[result.miss] += 1
        if result.miss == "dark":
            self.dark_peak += peak
        if self._run == 0:
            self.dropouts += 1
        self._run += 1
        self.longest = max(self.longest, self._run)

    def line(self, now: float) -> str:
        found = self.frames - self.lost
        parts = [
            f"tracking: {self.frames / max(now - self.started, 1e-6):.1f}fps",
            f"lost {100 * self.lost / self.frames:.1f}% ({self.lost}/{self.frames})",
            f"dropouts {self.dropouts}, longest {self.longest} frames",
        ]
        if self.misses:
            parts.append("misses " + ", ".join(f"{k} {n}" for k, n in self.misses.most_common()))
        if self.misses["dark"]:
            parts.append(f"peak when dark {self.dark_peak / self.misses['dark']:.0f}")
        if found:
            parts.append(
                f"marker area {self.area / found:.0f}px brightness {self.brightness / found:.0f}"
            )
        return "  ".join(parts)


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

        self.yield_to_mouse = config.yield_to_mouse
        self.yield_delay = config.yield_delay
        self._yield_until = 0.0

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._frames = 0
        self._lost = 0
        self._tracking = False
        self._position: tuple[float, float] | None = None
        self._frame: np.ndarray | None = None
        self._stats = _TrackingStats(time.monotonic())
        self._recording: _Recording | None = None
        self._next_trigger_check = 0.0

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
        if self._recording is not None:
            with contextlib.suppress(Exception):
                self._recording.close()
            self._recording = None

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
            self.yield_to_mouse = config.yield_to_mouse
            self.yield_delay = config.yield_delay

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

        if self.pause.active and not self._yielding():
            self.cursor.move_by(*self.mapper.update(smoothed))
        else:
            # Keep the mapper from carrying a delta across the pause, or across
            # someone else driving the cursor.
            self.mapper.reset()

        with self._lock:
            self._frames += 1
            if position is None:
                self._lost += 1
            self._tracking = result.found
            self._position = position
            self._frame = frame

        # The peak is only worth its full-frame scan when there is no marker.
        peak = 0 if result.found else int(gray.max())
        self._stats.add(result, peak)
        now = time.monotonic()
        if now - self._stats.started >= STATS_EVERY:
            log.info("%s", self._stats.line(now))
            self._stats.reset(now)
        self._record(frame, result, peak, now)

    def _record(self, frame: np.ndarray, result: TrackResult, peak: int, now: float) -> None:
        """Keep a recording going, or start one if the trigger file has appeared.

        Never allowed to stop the loop: this thread is someone's mouse, and a
        full disk or a codec that will not open is not a reason for it to stop.
        """
        try:
            if self._recording is None and now >= self._next_trigger_check:
                self._next_trigger_check = now + RECORD_CHECK_EVERY
                trigger = record_trigger()
                if trigger.exists():
                    trigger.unlink()
                    folder = config_dir() / "recordings" / time.strftime("%Y%m%d-%H%M%S")
                    self._recording = _Recording(folder, self.tracker.roi, now)
                    log.info("recording %.0fs of frames to %s", RECORD_SECONDS, folder)
            if self._recording is None:
                return
            if now >= self._recording.until:
                self._recording.close()
                log.info("recording finished: %s", self._recording.folder)
                self._recording = None
                return
            self._recording.add(frame, result, peak, now)
        except Exception:
            log.exception("recording failed - dropping it")
            if self._recording is not None:
                with contextlib.suppress(Exception):
                    self._recording.close()
            self._recording = None

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

    def _yielding(self) -> bool:
        """Whether to stand aside because something else is moving the cursor.

        The case this exists for: someone takes the real mouse to show you
        something. Two devices driving one cursor fight, and the head tracker
        wins by sheer frame rate, which makes the mouse feel broken.

        Detection is by position rather than by hooking the input stream -
        AccessCam knows where it last saw the cursor, so anything else that
        moved it shows up as a discrepancy and its own movement never does.
        That also covers devices a mouse hook would miss or misattribute,
        including the QuadStick.

        `yield_delay` is hold-off *after* the other device stops. A literal
        zero-second delay would never fire - mouse events arrive as a stream
        while a frame comes every 33ms - so the base behaviour is to yield for
        the frame in which foreign movement is seen, and the delay extends that.
        """
        if not self.yield_to_mouse:
            return False

        now = time.monotonic()
        if self.cursor.foreign_movement():
            self._yield_until = now + max(self.yield_delay, 0.0)
            # Adopt where the other device left the cursor, so resuming
            # continues from there instead of snapping back.
            self.cursor.sync()
            return True

        if now < self._yield_until:
            self.cursor.sync()
            return True

        return False

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

"""User configuration, stored as JSON in the platform's config directory.

Every default here is sourced from the module that owns it, so there is one
place to change any given value rather than two that can drift.

Unknown keys are reported and ignored rather than being an error: a config
written by a later version should not stop an earlier one from starting, and
being locked out by your own settings file is a bad failure for a tool someone
relies on to use their computer.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from accesscam.hotkeys import DEFAULT_HOTKEY
from accesscam.mapper import (
    DEFAULT_ACCEL_FLOOR,
    DEFAULT_ACCEL_KNEE,
    DEFAULT_ACCEL_SHARPNESS,
    DEFAULT_H_GAIN,
    DEFAULT_MAX_STEP,
    DEFAULT_V_GAIN,
)
from accesscam.mouse.base import DEFAULT_CLUTCH
from accesscam.smoothing import DEFAULT_BETA, DEFAULT_D_CUTOFF, DEFAULT_MIN_CUTOFF
from accesscam.tracker import (
    DEFAULT_MAX_AREA,
    DEFAULT_MAX_JUMP,
    DEFAULT_MIN_AREA,
    DEFAULT_MIN_CIRCULARITY,
    DEFAULT_THRESHOLD,
)

APP_NAME = "AccessCam"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return Path(base) / APP_NAME if base else Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg) / "accesscam" if xdg else Path.home() / ".config" / "accesscam"


def config_path() -> Path:
    return config_dir() / "config.json"


@dataclass
class Config:
    """Everything tunable, in one flat file the user can edit by hand."""

    # Camera
    device: int = 0
    backend: str = "dshow"
    width: int = 640
    height: int = 480
    fps: int = 30
    # Short exposure is what isolates the marker. -9 suited a bright room; -7
    # suited lamplight. Shorter also sharpens the sub-pixel centroid, so prefer
    # the shortest value that still holds the dot.
    exposure: int = -9

    # Tracking
    threshold: int = DEFAULT_THRESHOLD
    min_area: float = DEFAULT_MIN_AREA
    max_area: float = DEFAULT_MAX_AREA
    max_jump: float = DEFAULT_MAX_JUMP
    min_circularity: float = DEFAULT_MIN_CIRCULARITY
    # Region of interest, in frame pixels. Only blobs whose centre falls inside
    # this box are considered, which excludes fixed bright objects at the frame
    # edges (daylit windows, a lamp) that would otherwise rival the marker.
    #
    # There is no disabled state: the region is always in force, and a zero
    # width or height means "the whole frame" rather than "off". One always-live
    # box that is sometimes the size of the frame is easier to reason about than
    # a feature that silently is or is not applied - and it means the preview
    # always has a box to show and drag, instead of one appearing from nowhere.
    roi_x: int = 0
    roi_y: int = 0
    roi_w: int = 0
    roi_h: int = 0

    # Smoothing
    min_cutoff: float = DEFAULT_MIN_CUTOFF
    beta: float = DEFAULT_BETA
    d_cutoff: float = DEFAULT_D_CUTOFF

    # Mapping
    h_gain: float = DEFAULT_H_GAIN
    v_gain: float = DEFAULT_V_GAIN
    invert_x: bool = True
    invert_y: bool = False
    dead_zone: float = 0.0
    max_step: float = DEFAULT_MAX_STEP
    # Pointer acceleration, off until accel_floor drops below 1.0. The floor is
    # the fraction of full gain used while the marker is still: 0.35 cuts the
    # resting wander to roughly a third, which is what makes holding a caret
    # still for text selection workable. Tune it before touching the other two.
    accel_floor: float = DEFAULT_ACCEL_FLOOR
    accel_knee: float = DEFAULT_ACCEL_KNEE
    accel_sharpness: float = DEFAULT_ACCEL_SHARPNESS

    # Cursor
    # How far past a hard edge the tracked position may run while the
    # cursor stays pinned - the head-tracking equivalent of lifting a
    # mouse. Moving back spends the bank before the cursor follows, so the
    # head can return past centre. 0 disables it.
    clutch: float = DEFAULT_CLUTCH

    # Yield to another pointing device. On by default, unlike the clutch and
    # the acceleration curve: this one restores an expectation rather than
    # adding a behaviour, since two things moving one cursor at once is a
    # fight nobody asked for. `yield_delay` is extra hold-off *after* the other
    # device stops, in seconds; 0 resumes on the next frame.
    yield_to_mouse: bool = True
    yield_delay: float = 0.0

    # Control
    hotkey: str = DEFAULT_HOTKEY
    # Open straight to the tray with no window. Off by default: someone who has
    # just installed this needs to see the preview to aim the camera, and a
    # first run with no window at all looks like nothing happened.
    start_minimized: bool = False

    def roi(self) -> tuple[int, int, int, int]:
        """The (x, y, w, h) region searched, always a real box.

        A zero width or height resolves to the whole frame rather than to a
        degenerate box that would reject every blob.
        """
        if self.roi_w > 0 and self.roi_h > 0:
            return (self.roi_x, self.roi_y, self.roi_w, self.roi_h)
        return (0, 0, self.width, self.height)

    def roi_is_whole_frame(self) -> bool:
        """Whether the region covers everything, i.e. excludes nothing."""
        return self.roi() == (0, 0, self.width, self.height)

    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        """Adopt a region, clamped to the frame so it can never sit outside it."""
        x = max(0, min(int(x), self.width - 1))
        y = max(0, min(int(y), self.height - 1))
        self.roi_x, self.roi_y = x, y
        self.roi_w = max(1, min(int(w), self.width - x))
        self.roi_h = max(1, min(int(h), self.height - y))

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Read the config, falling back to defaults for anything absent."""
        target = path or config_path()
        if not target.exists():
            return cls()

        with target.open(encoding="utf-8") as handle:
            data = json.load(handle)

        known = {field.name for field in fields(cls)}
        unknown = set(data) - known
        if unknown:
            print(f"config: ignoring unknown setting(s): {', '.join(sorted(unknown))}")

        return cls(**{key: value for key, value in data.items() if key in known})

    def save(self, path: Path | None = None) -> Path:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(asdict(self), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return target

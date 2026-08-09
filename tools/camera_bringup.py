"""Milestone 1 bring-up tool: verify the camera and tune marker tracking.

Run this once the housing is mounted and a retroreflective dot is in place.
It answers the questions on the validation checklist in docs/HARDWARE.md:
what frame rate the camera really delivers, whether exposure can be driven low
enough to isolate the marker in a lit room, how far the dot travels across the
sensor over a comfortable range of head motion, and how much the tracked
position jitters while holding still.

Usage:
    python tools/camera_bringup.py --list
    python tools/camera_bringup.py --device 0

Keys:
    q / Esc   quit and print a summary
    [ / ]     lower / raise the brightness threshold
    - / =     shorten / lengthen exposure
    a         toggle auto exposure (for comparison only)
    j         measure jitter - hold still for a couple of seconds
    r         reset the travel-range measurement
    s         save a snapshot of the current frame
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2

from accesscam.camera import CameraError, CameraSettings, CameraSource, list_devices
from accesscam.tracker import DEFAULT_THRESHOLD, DotTracker

JITTER_SAMPLES = 120
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "bringup"

# Backends differ in what they will grant. On Windows, DirectShow has applied
# the full exposure range where MSMF clamped it, but which one negotiates
# MJPEG depends on the camera - so make it switchable and compare.
BACKENDS: dict[str, int | None] = {
    "auto": None,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "any": cv2.CAP_ANY,
}

HUD_COLOUR = (255, 255, 255)
MARKER_COLOUR = (0, 255, 0)
ALERT_COLOUR = (0, 165, 255)


@dataclass
class RangeTracker:
    """Tracks how far the marker travels, which calibrates the default gains."""

    min_x: float = float("inf")
    max_x: float = float("-inf")
    min_y: float = float("inf")
    max_y: float = float("-inf")

    def update(self, x: float, y: float) -> None:
        self.min_x = min(self.min_x, x)
        self.max_x = max(self.max_x, x)
        self.min_y = min(self.min_y, y)
        self.max_y = max(self.max_y, y)

    def reset(self) -> None:
        self.__init__()

    @property
    def span(self) -> tuple[float, float]:
        if self.min_x > self.max_x:
            return (0.0, 0.0)
        return (self.max_x - self.min_x, self.max_y - self.min_y)


@dataclass
class JitterMeasurement:
    """Collects centroid samples while the user holds still."""

    active: bool = False
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)
    result: tuple[float, float] | None = None

    def start(self) -> None:
        self.active = True
        self.xs.clear()
        self.ys.clear()
        self.result = None

    def add(self, x: float, y: float) -> None:
        if not self.active:
            return
        self.xs.append(x)
        self.ys.append(y)
        if len(self.xs) >= JITTER_SAMPLES:
            self.result = (statistics.pstdev(self.xs), statistics.pstdev(self.ys))
            self.active = False

    @property
    def progress(self) -> int:
        return len(self.xs)


def draw_overlay(
    frame,
    result,
    camera: CameraSource,
    tracker: DotTracker,
    ranges: RangeTracker,
    jitter: JitterMeasurement,
) -> None:
    if result.found:
        x, y = round(result.x), round(result.y)
        cv2.drawContours(frame, [result.contour], -1, MARKER_COLOUR, 1)
        cv2.drawMarker(frame, (x, y), MARKER_COLOUR, cv2.MARKER_CROSS, 20, 1)

    span_x, span_y = ranges.span
    lines = [
        (
            f"fps {camera.measured_fps:5.1f}   exposure {camera.exposure:3d} "
            f"(driver {camera.actual_exposure:g})   threshold {tracker.threshold:3d}"
        ),
        (
            f"dot  ({result.x:7.2f}, {result.y:7.2f})  area {result.area:6.1f}"
            if result.found
            else "dot  NOT FOUND"
        ),
        f"travel  x {span_x:6.1f} px   y {span_y:6.1f} px",
    ]
    if jitter.active:
        lines.append(f"measuring jitter... {jitter.progress}/{JITTER_SAMPLES} - hold still")
    elif jitter.result is not None:
        lines.append(f"jitter  x {jitter.result[0]:.3f} px   y {jitter.result[1]:.3f} px")

    for i, line in enumerate(lines):
        colour = ALERT_COLOUR if not result.found and i == 1 else HUD_COLOUR
        cv2.putText(
            frame, line, (8, 20 + i * 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA
        )


def print_summary(
    camera: CameraSource, tracker: DotTracker, ranges: RangeTracker, jitter: JitterMeasurement
) -> None:
    fmt = camera.actual_format()
    span_x, span_y = ranges.span

    print("\n--- Bring-up summary (docs/HARDWARE.md checklist) ---")
    print(f"  Format         {fmt['width']}x{fmt['height']} {fmt['codec']}")
    print(f"  Measured fps   {camera.measured_fps:.1f}  (driver reports {fmt['driver_fps']:.0f})")
    print(f"  Exposure       {camera.exposure}  (driver reports {fmt['exposure']})")
    print(f"  Threshold      {tracker.threshold}")
    print(f"  Marker travel  x {span_x:.1f} px, y {span_y:.1f} px")
    if jitter.result is not None:
        print(f"  Jitter (stdev) x {jitter.result[0]:.3f} px, y {jitter.result[1]:.3f} px")
    else:
        print("  Jitter         not measured (press 'j' during a run)")

    if fmt["codec"] != "MJPG":
        print("\n  WARNING: not in MJPEG mode - expect a lower frame rate at higher")
        print("           resolutions. Try --backend dshow or --backend msmf.")
    if abs(float(fmt["exposure"]) - camera.exposure) > 0.5:
        print(f"\n  WARNING: requested exposure {camera.exposure} but the driver held at")
        print(f"           {fmt['exposure']}. This backend is clamping the range; try")
        print("           the other one, or the marker may not isolate in a lit room.")
    if span_x and span_x < 40:
        print("\n  NOTE: very little travel recorded. Move your head through its full")
        print("        comfortable range with 'r' pressed first to calibrate gains.")


def run(args: argparse.Namespace) -> int:
    settings = CameraSettings(
        device=args.device,
        width=args.width,
        height=args.height,
        fps=args.fps,
        backend=BACKENDS[args.backend],
    )
    tracker = DotTracker(threshold=args.threshold)
    ranges = RangeTracker()
    jitter = JitterMeasurement()
    auto_exposure = False

    try:
        camera = CameraSource(settings)
        camera.open()
    except CameraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    fmt = camera.actual_format()
    print(f"Opened device {args.device}: {fmt['width']}x{fmt['height']} {fmt['codec']}")
    print("Press 'q' to quit. See the module docstring for the other keys.")

    window = "AccessCam bring-up"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                # An occasional dropped frame is normal on USB2; a persistent
                # failure surfaces as a frozen preview.
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            result = tracker.process(gray)
            if result.found:
                ranges.update(result.x, result.y)
                jitter.add(result.x, result.y)

            draw_overlay(frame, result, camera, tracker, ranges, jitter)
            cv2.imshow(window, frame)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            elif key == ord("["):
                tracker.threshold = max(0, tracker.threshold - 5)
            elif key == ord("]"):
                tracker.threshold = min(255, tracker.threshold + 5)
            elif key == ord("-"):
                camera.step_exposure(-1)
            elif key == ord("="):
                camera.step_exposure(1)
            elif key == ord("a"):
                auto_exposure = not auto_exposure
                if auto_exposure:
                    camera.enable_auto_exposure()
                else:
                    camera.disable_auto_exposure()
                    camera.set_exposure(camera.exposure)
                print(f"auto exposure {'on' if auto_exposure else 'off'}")
            elif key == ord("j"):
                jitter.start()
            elif key == ord("r"):
                ranges.reset()
                tracker.reset()
            elif key == ord("s"):
                SNAPSHOT_DIR.mkdir(exist_ok=True)
                path = SNAPSHOT_DIR / f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}.png"
                cv2.imwrite(str(path), frame)
                print(f"saved {path}")
    finally:
        print_summary(camera, tracker, ranges, jitter)
        camera.close()
        cv2.destroyAllWindows()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", type=int, default=0, help="camera index (default: 0)")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    parser.add_argument(
        "--backend",
        choices=sorted(BACKENDS),
        default="auto",
        help="capture backend; try dshow vs msmf if exposure or MJPEG misbehaves",
    )
    parser.add_argument("--list", action="store_true", help="probe for cameras and exit")
    args = parser.parse_args()

    if args.list:
        devices = list_devices()
        print("Readable camera indices:", devices if devices else "none found")
        return 0

    return run(args)


if __name__ == "__main__":
    sys.exit(main())

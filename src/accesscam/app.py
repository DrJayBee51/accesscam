"""The cursor-control pipeline: camera to tracker to smoother to mapper to mouse.

Headless by design at this milestone. There is no window to click on, so the
pause hotkey is the only control - and the whole thing therefore starts paused
and waits to be switched on deliberately.

Run with `python -m accesscam`.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

from accesscam.camera import CameraError, CameraSettings, CameraSource
from accesscam.config import Config, config_path
from accesscam.hotkeys import PauseController, create_listener, parse_hotkey
from accesscam.mapper import MapperSettings, RelativeMapper
from accesscam.mouse import CursorController, create_backend
from accesscam.mouse.fake import RecordingMouse
from accesscam.smoothing import PointSmoother, SmoothingSettings
from accesscam.tracker import DotTracker

BACKENDS = {
    "auto": None,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "v4l2": cv2.CAP_V4L2,
    "any": cv2.CAP_ANY,
}

STATUS_INTERVAL = 2.0


def build_camera(config: Config) -> CameraSource:
    camera = CameraSource(
        CameraSettings(
            device=config.device,
            width=config.width,
            height=config.height,
            fps=config.fps,
            backend=BACKENDS.get(config.backend),
        )
    )
    camera.open()
    camera.set_exposure(config.exposure)
    return camera


def list_devices(max_index: int = 8) -> int:
    """Probe camera indices and report enough to tell them apart.

    The index differs from machine to machine, and a laptop's built-in webcam
    frequently takes 0. The Arducam is distinguishable by granting 1920x1080,
    which lower-resolution webcams will not.
    """
    print("probing camera indices (this takes a few seconds)...\n")
    print(f"  {'idx':>3s}  {'granted at 1920x1080':>20s}  {'codec':>5s}   likely")
    found = 0
    for index in range(max_index):
        capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            continue
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        ok, _ = capture.read()
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)).strip()
        capture.release()
        if not ok:
            continue
        found += 1
        guess = "Arducam" if width >= 1920 else "other webcam"
        print(f"  {index:3d}  {f'{width}x{height}':>20s}  {codec:>5s}   {guess}")

    if not found:
        print("  no readable cameras found - check the USB connection")
        return 1
    print("\nSet the one you want with:  python -m accesscam --device N --write-config")
    return 0


def run(config: Config, dry_run: bool = False) -> int:
    tracker = DotTracker(
        threshold=config.threshold,
        min_area=config.min_area,
        max_area=config.max_area,
        max_jump=config.max_jump,
        min_circularity=config.min_circularity,
    )
    smoother = PointSmoother(
        SmoothingSettings(min_cutoff=config.min_cutoff, beta=config.beta, d_cutoff=config.d_cutoff)
    )
    mapper = RelativeMapper(
        MapperSettings(
            h_gain=config.h_gain,
            v_gain=config.v_gain,
            invert_x=config.invert_x,
            invert_y=config.invert_y,
            dead_zone=config.dead_zone,
            max_step=config.max_step,
        )
    )

    backend = RecordingMouse() if dry_run else create_backend()
    cursor = CursorController(backend, edge_resistance=config.edge_resistance)

    try:
        camera = build_camera(config)
    except CameraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    fmt = camera.actual_format()
    print(
        f"camera {config.device}: {fmt['width']}x{fmt['height']} {fmt['codec']} "
        f"exposure {camera.actual_exposure:g}"
    )
    if fmt["codec"] != "MJPG":
        print("  warning: not in MJPEG mode - expect a reduced frame rate")

    pause = PauseController()

    def announce(paused: bool) -> None:
        # Re-adopt the real cursor position on resume: it may have been moved
        # by other means while we were paused, and the mapper must not carry a
        # stale position across the gap.
        if not paused:
            cursor.sync()
            mapper.reset()
        print(f"\n>>> {'PAUSED' if paused else 'ACTIVE'}")

    pause.on_change(announce)

    hotkey = parse_hotkey(config.hotkey)
    listener = create_listener(hotkey, pause.toggle)
    try:
        listener.start()
    except Exception as exc:  # noqa: BLE001 - any failure here must be visible
        print(f"error: could not register {config.hotkey!r}: {exc}", file=sys.stderr)
        print("Refusing to start without a way to stop the cursor.", file=sys.stderr)
        camera.close()
        return 1

    print(f"pause hotkey: {config.hotkey.upper()}   (starts PAUSED - press it to take control)")
    if dry_run:
        print("dry run: the real cursor will not move")
    print("Ctrl+C to quit.\n")

    frames = 0
    lost = 0
    last_status = time.monotonic()

    try:
        while True:
            frame = camera.read()
            if frame is None:
                continue
            frames += 1

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            result = tracker.process(gray)
            position = result.position if result.found else None
            if position is None:
                lost += 1

            smoothed = smoother.update(position)

            if pause.active:
                cursor.move_by(*mapper.update(smoothed))
            else:
                # Keep the mapper from carrying a delta across the pause.
                mapper.reset()

            now = time.monotonic()
            if now - last_status >= STATUS_INTERVAL:
                state = "ACTIVE" if pause.active else "paused"
                tracked = "tracking" if result.found else "NO MARKER"
                print(
                    f"\r{state:6s} | {camera.measured_fps:4.1f}fps | {tracked:9s} | "
                    f"cursor {cursor.position[0]:8.1f},{cursor.position[1]:8.1f} | "
                    f"lost {100 * lost / max(frames, 1):3.0f}%",
                    end="",
                    flush=True,
                )
                last_status = now
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        listener.stop()
        camera.close()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="accesscam", description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="path to a config file")
    parser.add_argument("--device", type=int, default=None, help="camera index override")
    parser.add_argument("--hotkey", default=None, help="pause hotkey override, e.g. f9")
    parser.add_argument("--exposure", type=int, default=None, help="exposure override")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run the full pipeline without moving the real cursor",
    )
    parser.add_argument(
        "--write-config",
        action="store_true",
        help="write the current settings to the config file and exit",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="probe for cameras and exit - use this first on a new machine",
    )
    args = parser.parse_args()

    if args.list_devices:
        return list_devices()

    config = Config.load(args.config)
    if args.device is not None:
        config.device = args.device
    if args.hotkey is not None:
        config.hotkey = args.hotkey
    if args.exposure is not None:
        config.exposure = args.exposure

    if args.write_config:
        written = config.save(args.config)
        print(f"wrote {written}")
        return 0

    print(f"config: {args.config or config_path()}")
    return run(config, dry_run=args.dry_run)

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
from accesscam.engine import Engine
from accesscam.hotkeys import create_listener, parse_hotkey
from accesscam.mouse import CursorController, create_backend
from accesscam.mouse.fake import RecordingMouse

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


def warn_if_not_elevated() -> None:
    """Say so up front when hovering will not register on privileged windows.

    UIPI silently drops input from a medium-integrity process to a higher
    one. The cursor still moves, so nothing looks broken - the symptom is
    only that hover-driven UI stops responding, which is very hard to
    attribute without being told.
    """
    if sys.platform != "win32":
        return
    from accesscam.mouse.windows import is_elevated

    if not is_elevated():
        print("  note: not running as administrator. The cursor will move, but")
        print("        windows at higher privilege will not see it hover, so")
        print("        on-screen keyboards stop highlighting and UAC prompts")
        print("        ignore it. Relaunch from an Administrator terminal.")


def run(config: Config, dry_run: bool = False) -> int:
    backend = RecordingMouse() if dry_run else create_backend()
    cursor = CursorController(backend, clutch=config.clutch)

    try:
        camera = build_camera(config)
    except CameraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    engine = Engine(config, camera, cursor)

    fmt = camera.actual_format()
    print(
        f"camera {config.device}: {fmt['width']}x{fmt['height']} {fmt['codec']} "
        f"exposure {camera.actual_exposure:g}"
    )
    if fmt["codec"] != "MJPG":
        print("  warning: not in MJPEG mode - expect a reduced frame rate")

    roi = config.roi()
    if roi is not None:
        print(
            f"  region of interest: {roi[2]}x{roi[3]} at ({roi[0]}, {roi[1]}) "
            "- marker sought only inside it"
        )

    if config.accel_floor < 1.0:
        print(
            f"  acceleration: gain {config.accel_floor * config.h_gain:.1f} at rest, "
            f"{config.h_gain:.1f} when sweeping (knee {config.accel_knee:g} px/s)"
        )

    warn_if_not_elevated()

    pause = engine.pause

    def announce(paused: bool) -> None:
        # Re-adopting the cursor position on resume is the engine's business
        # now, and it subscribed first, so it has already happened here.
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

    engine.start()

    try:
        while engine.running:
            time.sleep(STATUS_INTERVAL)
            status = engine.status()
            state = "paused" if status.paused else "ACTIVE"
            tracked = "tracking" if status.tracking else "NO MARKER"
            print(
                f"\r{state:6s} | {status.fps:4.1f}fps | {tracked:9s} | "
                f"lost {100 * status.lost_fraction:3.0f}% | "
                f"peak {status.peak_demand:5.0f}px/frame | "
                f"clipped {100 * status.clipped_fraction:3.0f}%",
                end="",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        engine.stop()
        listener.stop()
        camera.close()

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="accesscam", description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None, help="path to a config file")
    parser.add_argument("--device", type=int, default=None, help="camera index override")
    parser.add_argument("--hotkey", default=None, help="pause hotkey override, e.g. f9")
    parser.add_argument("--exposure", type=int, default=None, help="exposure override")
    # Feel is tuned by trying values, not by reasoning about them, so the ones
    # that get iterated on are reachable without editing the config first.
    parser.add_argument("--h-gain", type=float, default=None, help="horizontal gain")
    parser.add_argument("--v-gain", type=float, default=None, help="vertical gain")
    parser.add_argument("--gain", type=float, default=None, help="both gains at once")
    parser.add_argument("--min-cutoff", type=float, default=None, help="smoothing at rest")
    parser.add_argument("--beta", type=float, default=None, help="how fast smoothing lets go")
    parser.add_argument("--clutch", type=float, default=None, help="edge over-travel bank")
    parser.add_argument(
        "--max-step", type=float, default=None, help="ceiling on cursor movement per frame"
    )
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
    if args.gain is not None:
        config.h_gain = config.v_gain = args.gain
    if args.h_gain is not None:
        config.h_gain = args.h_gain
    if args.v_gain is not None:
        config.v_gain = args.v_gain
    if args.min_cutoff is not None:
        config.min_cutoff = args.min_cutoff
    if args.beta is not None:
        config.beta = args.beta
    if args.clutch is not None:
        config.clutch = args.clutch
    if args.max_step is not None:
        config.max_step = args.max_step

    if args.write_config:
        written = config.save(args.config)
        print(f"wrote {written}")
        return 0

    print(f"config: {args.config or config_path()}")
    return run(config, dry_run=args.dry_run)

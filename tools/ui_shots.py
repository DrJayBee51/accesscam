"""Render each settings tab to a PNG, without a camera or a real cursor.

For documentation, for sharing, and for reviewing a layout change without
relaunching the application every time. Qt can screenshot its own window, so
this builds the real `MainWindow` over a fake camera and grabs each tab.

    python tools/ui_shots.py out/

The preview shows a synthetic frame rather than a capture. That is deliberate
and it is an honest likeness: at the exposures this runs at, the real feed is a
black field with the marker as the only bright thing, plus whatever stray
reflection is competing with it. It also means this can run while the
application itself holds the camera, which a second capture could not.

This wants a real desktop, unlike the UI tests. Qt's offscreen platform reports
a stand-in screen size and ships no fonts, so a shot taken under it is neither
the right dimensions nor the right typography - fine for asserting that two
cards match, useless as a picture of the application.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from accesscam import camera as camera_module  # noqa: E402
from accesscam.camera import DeviceInfo  # noqa: E402
from accesscam.config import Config  # noqa: E402
from accesscam.engine import Engine  # noqa: E402
from accesscam.mouse import CursorController  # noqa: E402
from accesscam.mouse.base import ScreenBounds  # noqa: E402
from accesscam.mouse.fake import RecordingMouse  # noqa: E402
from accesscam.ui.main_window import MainWindow  # noqa: E402

TABS = [
    (0, "accesscam-1-camera-and-marker.png"),
    (1, "accesscam-2-cursor-movement.png"),
    (2, "accesscam-3-application.png"),
]

PICKER = "accesscam-4-camera-picker.png"

# What the picker would find on a laptop with the IR camera plugged in: the
# built-in webcam holding index 0, which is precisely the situation that used
# to end a first run.
DEMO_DEVICES = [
    DeviceInfo(index=0, width=640, height=480, codec="YUY2"),
    DeviceInfo(index=1, width=1920, height=1080, codec="MJPG"),
]

# Settings chosen to show the features rather than to be anyone's defaults: a
# region that excludes something, and an acceleration curve with a visible knee.
DEMO = Config(
    h_gain=120.0,
    v_gain=90.0,
    accel_floor=0.35,
    accel_knee=25.0,
    accel_sharpness=3.0,
    min_cutoff=0.15,
    beta=0.4,
    roi_x=180,
    roi_y=120,
    roi_w=320,
    roi_h=260,
)


class DemoCamera:
    """A marker inside the region, and a bright distractor outside it."""

    measured_fps = 29.4
    exposure = -9

    def read(self) -> np.ndarray:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        ys, xs = np.ogrid[:480, :640]
        frame[(xs - 330) ** 2 + (ys - 250) ** 2 <= 30] = 245
        frame[(xs - 70) ** 2 + (ys - 60) ** 2 <= 260] = 255
        return frame

    def set_exposure(self, value: int) -> int:
        return value


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    engine = Engine(
        DEMO,
        DemoCamera(),
        CursorController(RecordingMouse(bounds=ScreenBounds(0, 0, 2560, 1440), start=(0, 0))),
    )
    window = MainWindow(engine, DEMO)
    window.show()

    # A frame for the preview, then both tabs shown once: a tab that has never
    # been current has not been laid out, and would be captured at the wrong size.
    window.preview.update_frame(DemoCamera().read(), (330.0, 250.0), True, DEMO.roi())
    for index, _ in TABS:
        window.tabs.setCurrentIndex(index)
        app.processEvents()

    for index, name in TABS:
        window.tabs.setCurrentIndex(index)
        for _ in range(4):
            app.processEvents()
        window.grab().save(str(out / name))
        print(f"  {out / name}")

    _shoot_picker(app, out)

    engine.stop()
    print(f"\n{window.width()} x {window.height()}")
    return 0


def _shoot_picker(app: QApplication, out: Path) -> None:
    """The camera picker, which is otherwise only visible by breaking a config.

    The probe is stubbed rather than run. It would open every real camera on
    the machine, take several seconds, and produce a different picture on every
    computer this is run on.
    """
    from accesscam.ui.first_run import CameraPicker

    camera_module.probe_devices = lambda *args, **kwargs: list(DEMO_DEVICES)

    picker = CameraPicker(Config(device=0))
    picker.show()
    picker.scan()
    for _ in range(4):
        app.processEvents()

    picker.grab().save(str(out / PICKER))
    print(f"  {out / PICKER}")
    picker.close()


if __name__ == "__main__":
    raise SystemExit(main())

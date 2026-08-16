"""The settings window.

Two tabs, split by the question being asked. *Camera & marker* answers "is the
dot being seen", and everything on it changes what the tracker gets. *Cursor
movement* answers "does the cursor feel right", and everything on it changes
what happens to the dot once found. Keeping them apart matters because the
first is diagnosis and the second is taste, and mixing them is how you end up
adjusting gain to fix an exposure problem.

The window stays usable while the cursor is live, as the SmartNav's does. That
is not a detail: the reason to open this window is usually that the cursor is
behaving badly, so a window that demanded a well-behaved cursor to operate
would be useless exactly when it is needed.
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from accesscam.config import Config, config_path
from accesscam.engine import Engine
from accesscam.ui.controls import Tuner
from accesscam.ui.curve import CurveWidget
from accesscam.ui.preview import PreviewWidget

REFRESH_MS = 33  # ~30Hz, matching the camera rather than outrunning it

STYLESHEET = """
QWidget { background: #17171a; color: #e4e4e8; font-size: 13px; }
QTabWidget::pane { border: 1px solid #2e2e34; border-radius: 6px; top: -1px; }
QTabBar::tab {
    background: #1e1e22; color: #a8a8b0; padding: 9px 20px;
    border: 1px solid #2e2e34; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 3px;
}
QTabBar::tab:selected { background: #26262c; color: #ffffff; }
QLabel#tunerName { font-weight: 600; }
QLabel#tunerKey { color: #7c7c86; font-family: Consolas, monospace; font-size: 11px; }
QLabel#tunerHelp { color: #9a9aa4; font-size: 11px; }
QLabel#tunerValue {
    font-family: Consolas, monospace; font-size: 14px; font-weight: 600; color: #6aa9ea;
}
QLabel#sectionHeading {
    color: #8c8c96; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}
QLabel#stat { font-family: Consolas, monospace; color: #c4c4cc; }
QLabel#stateBadge { font-weight: 700; font-size: 15px; padding: 6px 16px; border-radius: 5px; }
QPushButton {
    background: #2a2a31; border: 1px solid #3a3a43; border-radius: 5px;
    padding: 8px 16px; color: #e4e4e8;
}
QPushButton:hover { border-color: #6aa9ea; }
QPushButton:focus { border: 2px solid #6aa9ea; }
QPushButton#stepButton { font-size: 19px; font-weight: 700; padding: 0px; }
QPushButton#primary { background: #2f6fc0; border-color: #2f6fc0; font-weight: 600; }
QPushButton#primary:hover { background: #3a82da; }
QSlider::groove:horizontal { height: 5px; background: #34343c; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #6aa9ea; width: 20px; height: 20px;
    margin: -8px 0; border-radius: 10px;
}
QSlider:focus::handle:horizontal { background: #8dc2ff; }
QScrollArea { border: none; }
QFrame#card { background: #1c1c21; border: 1px solid #2b2b32; border-radius: 8px; }
"""


def heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionHeading")
    return label


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("tunerHelp")
    label.setWordWrap(True)
    return label


class MainWindow(QMainWindow):
    def __init__(
        self,
        engine: Engine,
        config: Config,
        config_file: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.engine = engine
        self.config = config
        self.config_file = config_file or config_path()

        self._last_frames = -1
        self._last_position: tuple[float, float] | None = None
        self._last_time: float | None = None
        self._speed = 0.0

        self.setWindowTitle("AccessCam")
        self.resize(1080, 720)
        self.setStyleSheet(STYLESHEET)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)
        layout.addWidget(self._build_header())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_camera_tab(), "Camera && marker")
        self.tabs.addTab(self._build_movement_tab(), "Cursor movement")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)

        self._load_into_controls()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(REFRESH_MS)

    # -- construction ------------------------------------------------------

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(14)

        self.state_badge = QLabel("PAUSED")
        self.state_badge.setObjectName("stateBadge")

        self.toggle_button = QPushButton("Take control  (F9)")
        self.toggle_button.setObjectName("primary")
        self.toggle_button.setMinimumWidth(190)
        self.toggle_button.clicked.connect(self.engine.pause.toggle)

        self.stat_label = QLabel("waiting for the camera…")
        self.stat_label.setObjectName("stat")

        row.addWidget(self.state_badge)
        row.addWidget(self.toggle_button)
        row.addStretch(1)
        row.addWidget(self.stat_label)
        return card

    def _scrolling(self, widgets: list[QWidget]) -> QScrollArea:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(4, 4, 12, 4)
        column.setSpacing(16)
        for widget in widgets:
            column.addWidget(widget)
        column.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(holder)
        return area

    def _tuner(self, *args, **kwargs) -> Tuner:
        tuner = Tuner(*args, **kwargs)
        tuner.valueChanged.connect(lambda value, key=tuner.key: self._on_change(key, value))
        self._tuners.append(tuner)
        return tuner

    def _build_camera_tab(self) -> QWidget:
        self._tuners: list[Tuner] = getattr(self, "_tuners", [])

        self.preview = PreviewWidget()
        self.preview.roiChanged.connect(self._on_roi_dragged)

        whole_frame = QPushButton("Reset to whole frame")
        whole_frame.clicked.connect(self._reset_roi)

        controls = self._scrolling(
            [
                heading("Region searched"),
                hint(
                    "Drag a box on the preview to limit where the marker is looked for. "
                    "Everything dimmed is ignored, which is how a daylit window stops "
                    "stealing the track."
                ),
                self._tuner("Left", "roi_x", 0, 639, 5, 0, suffix=" px"),
                self._tuner("Top", "roi_y", 0, 479, 5, 0, suffix=" px"),
                self._tuner("Width", "roi_w", 0, 640, 5, 0, suffix=" px"),
                self._tuner("Height", "roi_h", 0, 480, 5, 0, suffix=" px"),
                whole_frame,
                heading("Exposure and threshold"),
                self._tuner(
                    "Exposure",
                    "exposure",
                    -13,
                    0,
                    1,
                    0,
                    help_text="Shorter is better: it isolates the marker and sharpens the "
                    "centroid. Use the shortest that still holds the dot.",
                ),
                self._tuner(
                    "Threshold",
                    "threshold",
                    0,
                    255,
                    5,
                    0,
                    help_text="How bright a pixel must be to count. Raise it if something "
                    "else in the room gets tracked.",
                ),
                heading("Which blobs count"),
                self._tuner("Minimum area", "min_area", 1, 200, 1, 0, suffix=" px"),
                self._tuner("Maximum area", "max_area", 500, 20000, 250, 0, suffix=" px"),
                self._tuner(
                    "Minimum roundness",
                    "min_circularity",
                    0.0,
                    1.0,
                    0.05,
                    2,
                    help_text="Rejects elongated reflections. 0 disables the shape filter.",
                ),
            ]
        )
        controls.setMinimumWidth(370)
        controls.setMaximumWidth(430)

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(14)
        row.addWidget(self.preview, 1)
        row.addWidget(controls)
        return page

    def _build_movement_tab(self) -> QWidget:
        self._tuners = getattr(self, "_tuners", [])

        self.curve = CurveWidget()
        curve_card = QFrame()
        curve_card.setObjectName("card")
        curve_layout = QVBoxLayout(curve_card)
        curve_layout.setContentsMargins(12, 10, 12, 8)
        curve_layout.setSpacing(6)
        curve_layout.addWidget(heading("Gain against marker speed"))
        curve_layout.addWidget(self.curve)
        self.curve_note = QLabel()
        self.curve_note.setObjectName("tunerHelp")
        curve_layout.addWidget(self.curve_note)

        controls = self._scrolling(
            [
                heading("Speed"),
                self._tuner("Horizontal gain", "h_gain", 10, 200, 5, 0, suffix=" px/px"),
                self._tuner("Vertical gain", "v_gain", 10, 200, 5, 0, suffix=" px/px"),
                heading("Acceleration"),
                self._tuner(
                    "Precision floor",
                    "accel_floor",
                    0.10,
                    1.00,
                    0.05,
                    2,
                    help_text="Fraction of full gain while the marker is still. 1.00 turns "
                    "the curve off. Lower this first if you cannot hold a caret.",
                ),
                self._tuner(
                    "Knee speed",
                    "accel_knee",
                    5,
                    120,
                    5,
                    0,
                    suffix=" px/s",
                    help_text="Where you are halfway back to full gain. Lower it if long "
                    "sweeps feel sluggish.",
                ),
                self._tuner("Sharpness", "accel_sharpness", 1.0, 4.0, 0.1, 1),
                heading("Smoothing"),
                self._tuner(
                    "Calm at rest",
                    "min_cutoff",
                    0.05,
                    2.00,
                    0.05,
                    2,
                    help_text="Lower is steadier when still, at the cost of lag.",
                ),
                self._tuner(
                    "Release when moving",
                    "beta",
                    0.0,
                    1.5,
                    0.05,
                    2,
                    help_text="Higher lets the filter get out of the way faster.",
                ),
                heading("Edges"),
                self._tuner(
                    "Clutch",
                    "clutch",
                    0,
                    1500,
                    50,
                    0,
                    suffix=" px",
                    help_text="Over-travel banked at a screen edge, so you can re-centre "
                    "your head. 0 disables it.",
                ),
            ]
        )
        controls.setMinimumWidth(380)
        controls.setMaximumWidth(440)

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(12)
        left.addWidget(curve_card)
        left.addStretch(1)
        row.addLayout(left, 1)
        row.addWidget(controls)
        return page

    def _build_footer(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        path_label = QLabel(str(self.config_file))
        path_label.setObjectName("tunerHelp")

        revert = QPushButton("Revert to saved")
        revert.clicked.connect(self._revert)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)

        row.addWidget(path_label, 1)
        row.addWidget(revert)
        row.addWidget(save)
        return card

    # -- wiring ------------------------------------------------------------

    def _load_into_controls(self) -> None:
        # Materialise the region before showing it. A stored zero means "the
        # whole frame", and a Width box reading 0 next to a full-frame outline
        # would be a straightforward lie about what the tracker is doing.
        self.config.set_roi(*self.config.roi())
        for tuner in self._tuners:
            tuner.set_value(float(getattr(self.config, tuner.key)))
        self._refresh_curve()

    def _on_change(self, key: str, value: float) -> None:
        current = getattr(self.config, key)
        setattr(self.config, key, int(round(value)) if isinstance(current, int) else value)
        if key.startswith("roi_"):
            # Re-clamp: the four values move independently, so a wide box pushed
            # right can otherwise run off the frame and quietly exclude the marker.
            self.config.set_roi(
                self.config.roi_x, self.config.roi_y, self.config.roi_w, self.config.roi_h
            )
        self.engine.apply(self.config)
        if key in {"h_gain", "accel_floor", "accel_knee", "accel_sharpness"}:
            self._refresh_curve()

    def _on_roi_dragged(self, x: int, y: int, w: int, h: int) -> None:
        self.config.set_roi(x, y, w, h)

        shown = {}
        for tuner in self._tuners:
            if tuner.key.startswith("roi_"):
                tuner.set_value(float(getattr(self.config, tuner.key)))
                shown[tuner.key] = int(round(tuner.value()))
        # Read the values straight back off the controls. They quantise to their
        # own step, so taking the drag as authoritative would leave the numbers
        # on screen disagreeing with the box being used by a few pixels.
        self.config.set_roi(shown["roi_x"], shown["roi_y"], shown["roi_w"], shown["roi_h"])

        self.engine.apply(self.config)

    def _reset_roi(self) -> None:
        self._on_roi_dragged(0, 0, self.config.width, self.config.height)
        self.statusBar().showMessage("Searching the whole frame again", 4000)

    def _refresh_curve(self) -> None:
        self.curve.set_curve(
            self.config.h_gain,
            self.config.accel_floor,
            self.config.accel_knee,
            self.config.accel_sharpness,
        )
        at_rest = self.config.h_gain * self.config.accel_floor
        if self.config.accel_floor >= 1.0:
            self.curve_note.setText(
                "Acceleration is off — the gain is flat at every speed. "
                "Lower the precision floor to turn it on."
            )
        else:
            self.curve_note.setText(
                f"{at_rest:.0f} px/px while placing the cursor, "
                f"{self.config.h_gain:.0f} px/px when sweeping."
            )

    def _save(self) -> None:
        try:
            written = self.config.save(self.config_file)
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self.statusBar().showMessage(f"Saved to {written}", 4000)

    def _revert(self) -> None:
        self.config = Config.load(self.config_file)
        self._load_into_controls()
        self.engine.apply(self.config)
        self.statusBar().showMessage("Reverted to the saved settings", 4000)

    # -- the poll ----------------------------------------------------------

    def _refresh(self) -> None:
        status = self.engine.status()

        paused = status.paused
        self.state_badge.setText("PAUSED" if paused else "ACTIVE")
        self.state_badge.setStyleSheet(
            "background: #4a2020; color: #ff9d94;"
            if paused
            else "background: #1e4023; color: #86e39a;"
        )
        self.toggle_button.setText("Take control  (F9)" if paused else "Park the cursor  (F9)")

        tracked = "tracking" if status.tracking else "NO MARKER"
        self.stat_label.setText(
            f"{status.fps:4.1f} fps   |   {tracked}   |   "
            f"lost {100 * status.lost_fraction:3.0f}%   |   "
            f"clipped {100 * status.clipped_fraction:3.0f}%"
        )

        if status.frames != self._last_frames:
            self._last_frames = status.frames
            self._update_speed(status.position)
            self.preview.update_frame(
                self.engine.latest_frame(),
                status.position,
                status.tracking,
                self.config.roi(),
            )
            if self.tabs.currentIndex() == 1:
                self.curve.set_live_speed(self._speed if status.tracking else None)

    def _update_speed(self, position: tuple[float, float] | None) -> None:
        """Marker speed for the curve's live marker.

        Smoothed heavily on purpose. The instantaneous frame-to-frame speed is
        far too jumpy to read as a moving dot, and this is a readout rather than
        anything the mapper acts on.
        """
        now = time.monotonic()
        if position is None or self._last_position is None or self._last_time is None:
            self._last_position, self._last_time = position, now
            return

        dt = now - self._last_time
        if dt > 0:
            travelled = math.hypot(
                position[0] - self._last_position[0], position[1] - self._last_position[1]
            )
            self._speed += 0.25 * (travelled / dt - self._speed)
        self._last_position, self._last_time = position, now

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        self.timer.stop()
        super().closeEvent(event)


def launch(config: Config, config_file: Path | None = None, dry_run: bool = False) -> int:
    """Open the settings window with a live engine behind it."""
    from accesscam.app import build_camera
    from accesscam.camera import CameraError
    from accesscam.hotkeys import create_listener, parse_hotkey
    from accesscam.mouse import CursorController, create_backend
    from accesscam.mouse.fake import RecordingMouse

    # Before QApplication: creating the Windows backend is what makes the
    # process per-monitor DPI aware, and Qt adopts that rather than imposing
    # its own if it is already set. The other order leaves the two disagreeing
    # about what a pixel is, on a desktop that really is mixed-DPI.
    backend = RecordingMouse() if dry_run else create_backend()
    cursor = CursorController(backend, clutch=config.clutch)

    try:
        camera = build_camera(config)
    except CameraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    engine = Engine(config, camera, cursor)
    app = QApplication(sys.argv)
    window = MainWindow(engine, config, config_file)
    window.show()

    listener = None
    try:
        listener = create_listener(parse_hotkey(config.hotkey), engine.pause.toggle)
        listener.start()
    except Exception as exc:  # noqa: BLE001 - visible, but not fatal with a window
        window.statusBar().showMessage(f"Hotkey {config.hotkey!r} unavailable: {exc}")

    engine.start()
    try:
        return app.exec()
    finally:
        engine.stop()
        if listener is not None:
            listener.stop()
        camera.close()

"""The settings window.

Three tabs, split by the question being asked. *Camera & Marker* answers "is the
dot being seen", and everything on it changes what the tracker gets. *Cursor
Movement* answers "does the cursor feel right", and everything on it changes
what happens to the dot once found. Keeping those two apart matters because the
first is diagnosis and the second is taste, and mixing them is how you end up
adjusting gain to fix an exposure problem.

*Application* is a third category rather than a drawer for leftovers: which
camera to use, whether to start at logon, and how to quit. None of it answers
either of the other two questions, and the camera choice in particular belongs
nowhere else - it is not a tracking-quality setting, it is which hardware to
point at.

The window stays usable while the cursor is live, as the SmartNav's does. That
is not a detail: the reason to open this window is usually that the cursor is
behaving badly, so a window that demanded a well-behaved cursor to operate
would be useless exactly when it is needed.
"""

from __future__ import annotations

import contextlib
import math
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QAbstractNativeEventFilter, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from accesscam import __version__, single_instance, startup
from accesscam.config import Config, config_path
from accesscam.engine import Engine
from accesscam.log import log
from accesscam.ui.controls import Tuner
from accesscam.ui.curve import CurveWidget
from accesscam.ui.help import HelpButton
from accesscam.ui.preview import PreviewWidget
from accesscam.ui.tray import Tray

REFRESH_MS = 33  # ~30Hz, matching the camera rather than outrunning it

# Preview height as a share of the monitor's height. A quarter puts it at
# 360px on a 1440p screen, which is large enough to grab the region's corner
# handles with a head-tracked cursor.
PREVIEW_SHARE = 1 / 4

# How much wider the settings columns sit than their content strictly needs.
# At 1.0 the sliders are squeezed against the step buttons; the extra goes
# almost entirely into slider length, which is what is being aimed at.
RIGHT_CARD_SCALE = 1.35

# Gap between the two cards on a tab. Named because the Application tab's single
# card has to span both of them plus this.
TAB_SPACING = 16

# How often to look for a system tray that was not there at startup. Checking
# is a single cheap call, and the shell it is waiting for takes seconds.
_TRAY_RETRY_INTERVAL = 1.0

# One broadcast lands on every top-level window we own; treat arrivals inside
# this window as the same request.
_REVEAL_DEBOUNCE = 1.0

STYLESHEET = """
QWidget { background: #17171a; color: #e4e4e8; font-size: 13px; }
/* Labels take the surface behind them, or every one inside a card paints a
   page-coloured rectangle over it. */
QLabel { background: transparent; }
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
QLabel#roiReadout {
    font-family: Consolas, monospace; color: #6aa9ea; font-size: 12px;
    padding: 7px 10px; background: #1f242c; border: 1px solid #2f3a48; border-radius: 5px;
}
QLabel#tunerValue {
    font-family: Consolas, monospace; font-size: 14px; font-weight: 600; color: #6aa9ea;
}
QLabel#sectionHeading {
    color: #8c8c96; font-size: 11px; font-weight: 700; letter-spacing: 1px;
}
QPushButton#stateButton {
    font-weight: 700; font-size: 14px; letter-spacing: 1px; padding: 9px 18px;
}
QPushButton#stateButton[state="active"] {
    background: #1e4023; border-color: #2f7038; color: #86e39a;
}
QPushButton#stateButton[state="active"]:hover { background: #255030; }
QPushButton#stateButton[state="paused"] {
    background: #4a2020; border-color: #7a3232; color: #ff9d94;
}
QPushButton#stateButton[state="paused"]:hover { background: #5c2828; }
QToolButton#helpButton {
    background: #24242b; border: 1px solid #3d3d47; border-radius: 10px;
    color: #8fbdf0; font-weight: 700; font-size: 12px;
}
QToolButton#helpButton:hover { background: #2f3a48; border-color: #6aa9ea; }
QToolButton#helpButton:focus { border: 2px solid #6aa9ea; }
QFrame#helpPopup { background: #23232a; border: 1px solid #414150; border-radius: 7px; }
QLabel#helpText { color: #d6d6de; font-size: 12px; background: transparent; }
QPushButton {
    background: #2a2a31; border: 1px solid #3a3a43; border-radius: 5px;
    padding: 8px 16px; color: #e4e4e8;
}
QPushButton:hover { border-color: #6aa9ea; }
QPushButton:focus { border: 2px solid #6aa9ea; }
QPushButton#stepButton { font-size: 19px; font-weight: 700; padding: 0px; }
QPushButton#primary { background: #2f6fc0; border-color: #2f6fc0; font-weight: 600; }
QPushButton#primary:hover { background: #3a82da; }
QPushButton#danger { background: #4a2020; border-color: #7a3232; color: #ff9d94; }
QPushButton#danger:hover { background: #5c2828; border-color: #a04444; }
QWidget#rowGroup { background: transparent; }
QCheckBox { background: transparent; spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border-radius: 4px;
    border: 1px solid #3d3d47; background: #24242b; }
QCheckBox::indicator:hover { border-color: #6aa9ea; }
QCheckBox::indicator:checked { background: #2f6fc0; border-color: #2f6fc0; }
QCheckBox:disabled { color: #6a6a74; }
QComboBox { background: #24242b; border: 1px solid #3d3d47; border-radius: 5px;
    padding: 7px 10px; }
QComboBox:hover { border-color: #6aa9ea; }
QComboBox QAbstractItemView { background: #24242b; border: 1px solid #3d3d47;
    selection-background-color: #2f6fc0; }
/* One flat bar the whole way across, with the handle as the only mark. A
   filled sub-page made each slider look like a different control depending on
   where its value happened to sit.

   Pseudo-states go AFTER the sub-control: `::handle:horizontal:focus`, never
   `:focus::handle:horizontal`. Qt mis-parses the latter and applies the
   declaration to the whole slider, which painted the widget's full height and
   left the groove looking like two bars with a gap down the middle. */
QSlider::groove:horizontal { height: 4px; background: #4a7cad; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #4a7cad; border-radius: 2px; }
QSlider::add-page:horizontal { background: #4a7cad; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #cfe6ff; width: 14px; height: 20px;
    margin: -8px 0; border-radius: 3px;
}
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::handle:horizontal:focus { background: #ffffff; }
QScrollArea { border: none; }
QStatusBar { color: #9a9aa4; }
QStatusBar::item { border: none; }
QFrame#card { background: #1c1c21; border: 1px solid #2b2b32; border-radius: 8px; }
"""


def heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionHeading")
    return label


def _is_elevated() -> bool:
    """Whether this process can deliver input to privileged windows.

    True everywhere but Windows: UIPI is a Windows mechanism, and a warning
    about it elsewhere would be noise about a problem that cannot occur.
    """
    if sys.platform != "win32":
        return True

    from accesscam.mouse.windows import is_elevated

    return is_elevated()


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("tunerHelp")
    label.setWordWrap(True)
    return label


def _rows(*items) -> QWidget:
    """Wrap layouts and widgets into one widget, for the column builder."""
    holder = QWidget()
    holder.setObjectName("rowGroup")  # transparent, or it paints over its card
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(8)
    for item in items:
        if isinstance(item, QWidget):
            column.addWidget(item)
        else:
            column.addLayout(item)
    return holder


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

        # Set by whoever owns the tray, if there is one. Without a tray there is
        # nowhere to hide to, so closing has to mean closing.
        self.hides_to_tray = False
        self.quit_requested = False
        self.tray = None

        self.setWindowTitle(f"AccessCam {__version__}")
        self.setStyleSheet(STYLESHEET)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(14)

        self.elevation_banner = self._build_elevation_banner()
        layout.addWidget(self.elevation_banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_camera_tab(), "Camera && Marker")
        self.tabs.addTab(self._build_movement_tab(), "Cursor Movement")
        self.tabs.addTab(self._build_application_tab(), "Application")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)

        # Build the status bar now rather than letting the first message create
        # it. QMainWindow makes it on demand, so the first "Saved" or "Reverted"
        # would appear *after* the window size was fixed - and the height it
        # needed came out of the cards, which visibly shrank the moment a
        # message was shown for the first time and never grew back.
        status = self.statusBar()
        status.setSizeGripEnabled(False)  # nothing to grip: the window is fixed

        self._load_into_controls()
        self._match_card_widths()
        self._tidy_button_focus()
        self._lock_size()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(REFRESH_MS)

    # -- construction ------------------------------------------------------

    def _build_elevation_banner(self) -> QWidget:
        """A standing warning while AccessCam lacks administrator rights.

        Not a dialog. UIPI makes an unelevated AccessCam *look* like it works -
        the cursor moves, because the cursor is global - while every window at
        higher integrity ignores the pointer hovering over it. On-screen
        keyboards stop highlighting, UAC prompts do not respond, and nothing
        anywhere says why. A dialog would be dismissed in the first minute and
        the symptom met an hour later; this stays until the cause is gone.

        Hidden entirely when elevated, so the normal case pays nothing for it.
        """
        banner = QFrame()
        banner.setObjectName("elevationBanner")
        banner.setStyleSheet(
            "#elevationBanner { background: #4a3410; border: 1px solid #7a5a1e; "
            "border-radius: 6px; }"
        )
        row = QHBoxLayout(banner)
        row.setContentsMargins(12, 7, 12, 7)
        row.setSpacing(12)

        # One line, deliberately. The window is fixed-size and sits 74px under
        # what a small laptop screen can show; a two-line banner spends all of
        # that and the layout starts clamping. The detail lives in the help
        # button beside it, where there is room for it.
        message = QLabel("Not running as administrator — hovering will be ignored")
        message.setToolTip(
            "Windows blocks a normal-privilege program from delivering input to a "
            "higher-privilege window. The cursor still moves, because the cursor is "
            "global, but the window under it never receives the hover: on-screen "
            "keyboards stop highlighting keys, UAC prompts do not respond, and "
            "anything running as administrator ignores the pointer entirely."
        )
        row.addWidget(message, 0)
        row.addStretch(1)

        self.elevate_button = QPushButton("Restart as administrator")
        self.elevate_button.clicked.connect(self._restart_elevated)
        row.addWidget(self.elevate_button, 0, Qt.AlignmentFlag.AlignVCenter)

        # Visible from the start so that `_lock_size` measures the window with
        # the strip in it. The window is fixed-size: revealing the banner after
        # locking takes its height out of the tabs instead, and the two tabs do
        # not give it up equally, which breaks the matched card heights.
        banner.setVisible(not _is_elevated())
        return banner

    def _restart_elevated(self) -> None:
        """Hand over to an elevated copy, then get out of its way.

        Quitting matters as much as starting: a camera cannot be opened twice,
        and the new copy is already waiting for this one to let go of it.
        """
        outcome = startup.relaunch_elevated()
        if not outcome.ok:
            QMessageBox.warning(self, "Could not restart as administrator", outcome.message)
            return

        log.info("handed over to an elevated copy - quitting")
        self.quit_requested = True
        QApplication.quit()

    def _scrolling(self, widgets: list[QWidget], card: bool = False) -> QScrollArea:
        inner = QFrame()
        if card:
            inner.setObjectName("card")
            inner.setContentsMargins(0, 0, 0, 0)
        column = QVBoxLayout(inner)
        column.setContentsMargins(*((14, 12, 14, 14) if card else (4, 4, 12, 4)))
        column.setSpacing(16)
        for widget in widgets:
            column.addWidget(widget)
        # Spare height inside the card, below the content. The card itself
        # stretches to fill the tab so it matches the card beside it; without
        # this the extra space would be shared out between the controls and
        # space them apart instead.
        column.addStretch(1)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(inner)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setMinimumHeight(inner.sizeHint().height())
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
        self._size_preview()

        preview_card = self._preview_card = QFrame()
        preview_card.setObjectName("card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 12, 14, 14)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(heading("What the tracker sees"))
        # Centred in whatever height the card ends up with, so it sits opposite
        # the middle of the controls rather than clinging to the heading.
        preview_layout.addStretch(1)
        preview_layout.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_layout.addStretch(1)

        controls = self._scrolling(
            [
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
            ],
            card=True,
        )
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(TAB_SPACING)

        self._camera_controls = controls
        row.addWidget(preview_card)
        row.addWidget(controls)
        row.addStretch(1)
        return page

    def _tidy_button_focus(self) -> None:
        """Let buttons take focus from Tab but not from a click.

        A click otherwise leaves the focus ring lit on whatever was last
        pressed, which reads as "this control is still doing something" long
        after it has finished. Sliders are deliberately left alone: focusing one
        by clicking it is how you then drive it with the arrow keys, and there
        the lit handle is telling the truth about which slider they will move.
        """
        for button in self.findChildren(QAbstractButton):
            button.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def _match_card_widths(self) -> None:
        """Give the two tabs the same column widths.

        The left cards both take the preview's width, so the curve sits over
        exactly the ground the preview does and switching tabs does not shift
        everything sideways. The right cards take a share more than their
        content strictly needs - at their natural width the sliders are cramped
        against the step buttons, and a slider too short to aim at is a poor
        trade for a narrower window.
        """
        left = self._preview_card.sizeHint().width()
        self._preview_card.setFixedWidth(left)
        self._curve_card.setFixedWidth(left)

        natural = self._camera_controls.widget().sizeHint().width()
        right = int(natural * RIGHT_CARD_SCALE)
        self._camera_controls.setFixedWidth(right)
        self._movement_controls.setFixedWidth(right)

        # The Application tab has one card rather than two, so it spans the
        # width both of the others occupy. Left at its natural width it clipped
        # the camera row and left most of the tab empty beside it.
        self._application_controls.setFixedWidth(left + right + TAB_SPACING)

    def _lock_size(self) -> None:
        """Fix the window at the size its content needs.

        Everything is visible at that size on both tabs, so resizing could only
        add empty space. Fixing it also means the controls never move between
        sessions, which matters more here than usual: hitting a target with a
        head-tracked cursor is far easier when the target is where it was last
        time.

        Still clamped to the screen. The preview scales with the monitor, so on
        a small display the natural size could otherwise exceed what is there
        to show it on.
        """
        # Measure every tab and take the largest. Sizing to the first alone
        # would clip whichever of the others needs more room.
        needed = None
        for index in range(self.tabs.count()):
            self.tabs.setCurrentIndex(index)
            hint = self.sizeHint()
            needed = hint if needed is None else needed.expandedTo(hint)
        self.tabs.setCurrentIndex(0)

        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            needed.setWidth(min(needed.width(), available.width() - 60))
            needed.setHeight(min(needed.height(), available.height() - 90))

        self.setFixedSize(needed)

    def _size_preview(self) -> None:
        """Fix the preview to a share of the monitor's height.

        Tied to the screen rather than the window so it stays the same physical
        size on every machine, which matters when the same settings are carried
        between a four-screen desktop and a three-screen one.
        """
        screen = self.screen() or QApplication.primaryScreen()
        height = int(screen.availableGeometry().height() * PREVIEW_SHARE) if screen else 360
        aspect = self.config.width / max(self.config.height, 1)
        self.preview.setFixedSize(int(height * aspect), height)

    def _build_movement_tab(self) -> QWidget:
        self._tuners = getattr(self, "_tuners", [])

        self.curve = CurveWidget()

        # The acceleration controls live inside the plot's own card, directly
        # under it. They are the three values that draw the curve, so putting
        # them across the page from it meant looking in one place while
        # changing something in another.
        curve_card = self._curve_card = QFrame()
        curve_card.setObjectName("card")
        curve_layout = QVBoxLayout(curve_card)
        curve_layout.setContentsMargins(14, 12, 14, 14)
        curve_layout.setSpacing(6)
        curve_layout.addWidget(heading("Gain against marker speed"))
        curve_layout.addWidget(self.curve)
        curve_layout.addSpacing(10)
        curve_layout.addWidget(heading("Acceleration"))
        curve_layout.addSpacing(2)
        for tuner in (
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
            self._tuner(
                "Sharpness",
                "accel_sharpness",
                1.0,
                4.0,
                0.1,
                1,
                help_text="How abruptly the gain climbs through the knee. Higher is a "
                "more definite switch between precise and fast; lower blends the two.",
            ),
        ):
            curve_layout.addWidget(tuner)
        curve_layout.addStretch(1)

        controls = self._scrolling(
            [
                heading("Speed"),
                self._tuner("Horizontal gain", "h_gain", 10, 200, 5, 0, suffix=" px/px"),
                self._tuner("Vertical gain", "v_gain", 10, 200, 5, 0, suffix=" px/px"),
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
            ],
            card=True,
        )
        controls.setMinimumWidth(380)
        controls.setMaximumWidth(440)

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(14)

        self._movement_controls = controls
        row.addWidget(curve_card)
        row.addWidget(controls)
        row.addStretch(1)
        return page

    def _build_application_tab(self) -> QWidget:
        """Settings about the application rather than about the tracking.

        A third category, not a drawer for leftovers: the other two tabs answer
        "is the dot seen" and "does the cursor feel right", and none of this
        answers either. The camera choice in particular belongs nowhere else -
        it is not a tracking-quality setting, it is which hardware to use.
        """
        self.camera_choice = QComboBox()
        self.camera_choice.setMinimumWidth(320)
        self.camera_choice.addItem(f"Camera {self.config.device} (in use)", self.config.device)
        self.camera_choice.activated.connect(self._on_camera_chosen)

        rescan = QPushButton("Scan for cameras")
        rescan.clicked.connect(self._rescan_cameras)

        camera_row = QHBoxLayout()
        camera_row.setSpacing(10)
        camera_row.addWidget(self.camera_choice, 1)
        camera_row.addWidget(rescan)
        camera_row.addWidget(
            HelpButton(
                "Which camera to track with. The index differs from machine to "
                "machine, and a laptop's built-in webcam frequently takes 0.\n\n"
                "Scanning opens every index in turn to see what answers, which "
                "takes a few seconds and briefly stops tracking — the camera in "
                "use has to be released before anything else can look at it.\n\n"
                "Switching cameras reopens the capture. If the new one cannot be "
                "opened, the old one is put back.",
                "the camera",
            )
        )

        self.camera_note = QLabel("Scan to see what else is connected.")
        self.camera_note.setObjectName("tunerHelp")
        self.camera_note.setWordWrap(True)

        self.start_minimised_box = QCheckBox("Start minimised to the tray")
        self.start_minimised_box.setChecked(self.config.start_minimized)
        self.start_minimised_box.toggled.connect(self._on_start_minimised)

        # One query, not three: each of these would otherwise spawn its own
        # schtasks every time the window opens.
        logon = startup.state()

        self.run_at_logon_box = QCheckBox("Start when I log in")
        self.run_at_logon_box.setEnabled(logon.supported)
        self.run_at_logon_box.setChecked(logon.enabled)
        self.run_at_logon_box.toggled.connect(self._on_run_at_logon)

        self.logon_note = QLabel()
        self.logon_note.setObjectName("tunerHelp")
        self.logon_note.setWordWrap(True)
        self._refresh_logon_note(logon)

        logon_row = QHBoxLayout()
        logon_row.setSpacing(8)
        logon_row.addWidget(self.run_at_logon_box)
        logon_row.addWidget(
            HelpButton(
                "Registers a scheduled task that runs AccessCam at logon with "
                "highest privileges.\n\nIt has to be a task rather than the usual "
                "startup shortcut, because AccessCam needs to run elevated — "
                "Windows otherwise stops the cursor registering as a hover on "
                "anything running at higher privilege, such as an on-screen "
                "keyboard.\n\nCreating the task needs administrator rights, so "
                "this only works when AccessCam itself was started as "
                "administrator.",
                "starting at logon",
            )
        )
        logon_row.addStretch(1)

        quit_button = QPushButton("Quit AccessCam")
        quit_button.setObjectName("danger")
        quit_button.setMinimumWidth(180)
        quit_button.clicked.connect(self._confirm_quit)

        quit_row = QHBoxLayout()
        quit_row.addWidget(quit_button)
        quit_row.addStretch(1)

        controls = self._scrolling(
            [
                heading("Camera"),
                _rows(camera_row, self.camera_note),
                heading("Starting up"),
                self.start_minimised_box,
                _rows(logon_row, self.logon_note),
                heading("Closing"),
                hint(
                    "Closing the window hides AccessCam to the tray and it keeps "
                    "driving the cursor. Quitting stops it entirely."
                ),
                _rows(quit_row),
            ],
            card=True,
        )

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(12, 12, 12, 12)
        row.setSpacing(TAB_SPACING)
        row.addWidget(controls)
        row.addStretch(1)
        self._application_controls = controls
        return page

    def _build_footer(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(10)

        # The state indicator *is* the toggle. Two controls for one piece of
        # state left the question of which one to read when they disagreed.
        self.state_button = QPushButton("PAUSED  (F9)")
        self.state_button.setObjectName("stateButton")
        self.state_button.setMinimumWidth(170)
        self.state_button.clicked.connect(self.engine.pause.toggle)

        reset_roi = QPushButton("Reset ROI")
        reset_roi.clicked.connect(self._reset_roi)

        revert = QPushButton("Revert to saved")
        revert.clicked.connect(self._revert)
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self._save)

        row.addWidget(self.state_button)
        row.addSpacing(12)
        row.addWidget(reset_roi)
        row.addWidget(
            HelpButton(
                "The region searched is the part of the camera image the marker is "
                "looked for in. Everything outside it is dimmed on the preview and "
                "ignored by the tracker, which is how a daylit window stops stealing "
                "the track.\n\nDrag the corner handles to resize it, or drag inside it "
                "to move it. With the preview focused, the arrow keys move it and "
                "Shift+arrows resize it.\n\nReset ROI returns it to the whole frame.",
                "the region searched",
            )
        )
        row.addStretch(1)
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
        self.engine.apply(self.config)
        # The plot is normalised, so the gains no longer redraw it - only the
        # three values that change the curve's shape do.
        if key.startswith("accel_"):
            self._refresh_curve()

    def _on_roi_dragged(self, x: int, y: int, w: int, h: int) -> None:
        self.config.set_roi(x, y, w, h)
        self.engine.apply(self.config)

    def _reset_roi(self) -> None:
        self.config.set_roi(0, 0, self.config.width, self.config.height)
        self.engine.apply(self.config)
        self.statusBar().showMessage("Searching the whole frame again", 4000)

    # -- application settings ----------------------------------------------

    def _rescan_cameras(self) -> None:
        """Enumerate cameras, which means letting go of the one in use.

        Every index has to be opened to find out what is there, and an index
        already held by a running capture will not open twice - so tracking
        stops for the duration. It is an explicit button rather than something
        that happens on opening the tab for exactly that reason.
        """
        from accesscam.camera import probe_devices

        self.camera_note.setText("Scanning…")
        QApplication.processEvents()

        was_running = self.engine.running
        self.engine.stop()
        self.engine.camera.close()

        try:
            devices = probe_devices()
        finally:
            reopened = self._open_camera(self.config.device)
            if reopened is not None:
                self.engine.use_camera(reopened)
            if was_running:
                self.engine.start()

        self.camera_choice.clear()
        for device in devices:
            self.camera_choice.addItem(device.label, device.index)
        if not devices:
            self.camera_choice.addItem(f"Camera {self.config.device}", self.config.device)

        index = self.camera_choice.findData(self.config.device)
        self.camera_choice.setCurrentIndex(max(index, 0))
        self.camera_note.setText(
            f"Found {len(devices)} camera{'s' if len(devices) != 1 else ''}."
            if devices
            else "No cameras answered. Check the USB connection."
        )

    def _open_camera(self, device: int):
        """Open one camera index, or None if it will not open."""
        from accesscam.app import build_camera
        from accesscam.camera import CameraError

        wanted = replace(self.config, device=device)
        try:
            return build_camera(wanted)
        except CameraError:
            return None

    def _on_camera_chosen(self, _row: int) -> None:
        device = self.camera_choice.currentData()
        if device is None or device == self.config.device:
            return

        was_running = self.engine.running
        self.engine.stop()
        self.engine.camera.close()

        camera = self._open_camera(device)
        if camera is None:
            # Put the old one back rather than leaving the user with no
            # tracking at all and a dialog to dismiss using a cursor that has
            # just stopped working.
            restored = self._open_camera(self.config.device)
            if restored is not None:
                self.engine.use_camera(restored)
            if was_running:
                self.engine.start()
            self.camera_choice.setCurrentIndex(
                max(self.camera_choice.findData(self.config.device), 0)
            )
            QMessageBox.warning(
                self,
                "Could not open that camera",
                f"Camera {device} would not open, so camera {self.config.device} is still in use.",
            )
            return

        self.config.device = device
        self.engine.use_camera(camera)
        if was_running:
            self.engine.start()
        self.statusBar().showMessage(
            f"Now tracking with camera {device}. Save settings to keep it.", 6000
        )

    def _on_start_minimised(self, checked: bool) -> None:
        self.config.start_minimized = checked
        if self.tray is not None:
            self.tray.minimised_action.setChecked(checked)

    def _refresh_logon_note(self, logon: startup.State | None = None) -> None:
        """Say what is actually registered, not what the checkbox implies.

        A task created by an earlier version keeps the command it was made
        with, so the box can read "on" while the wrong thing runs at logon.
        """
        logon = logon or startup.state()
        if not logon.supported:
            self.logon_note.setText("Only wired up for Windows so far.")
        elif logon.stale:
            self.logon_note.setText(
                "The registered task runs an older command. Untick and re-tick "
                "to update it — you will need AccessCam running as administrator."
            )
        elif logon.enabled:
            self.logon_note.setText("Registered as a scheduled task, elevated.")
        else:
            self.logon_note.setText("")

    def _on_run_at_logon(self, checked: bool) -> None:
        outcome = startup.enable() if checked else startup.disable()
        if outcome.ok:
            self._refresh_logon_note()
            self.statusBar().showMessage(
                "AccessCam will start when you log in."
                if checked
                else "AccessCam will no longer start when you log in.",
                6000,
            )
            return

        # Put the box back: it reports what is registered, not what was wanted.
        self.run_at_logon_box.blockSignals(True)
        self.run_at_logon_box.setChecked(not checked)
        self.run_at_logon_box.blockSignals(False)
        QMessageBox.warning(self, "Could not change the logon task", outcome.message)

    def _confirm_quit(self) -> None:
        """Quit, but ask first.

        For someone whose pointer this *is*, quitting by accident means losing
        the means to relaunch it - recovery is the fallback input device. One
        dialog is a fair price.
        """
        answer = QMessageBox.question(
            self,
            "Quit AccessCam?",
            "The cursor will stop responding to head movement.\n\n"
            "Closing the window instead keeps AccessCam running in the tray.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.quit_requested = True
            QApplication.quit()

    def _refresh_curve(self) -> None:
        self.curve.set_curve(
            self.config.accel_floor,
            self.config.accel_knee,
            self.config.accel_sharpness,
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
        if self.tray is not None:
            self.tray.set_paused(paused)

        state = "paused" if paused else "active"
        if self.state_button.property("state") != state:
            self.state_button.setText("PAUSED  (F9)" if paused else "ACTIVE  (F9)")
            self.state_button.setProperty("state", state)
            # Re-polish, or the stylesheet keeps painting the colour the button
            # had when it was built.
            self.state_button.style().unpolish(self.state_button)
            self.state_button.style().polish(self.state_button)

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

    def reveal(self) -> None:
        """Bring the window back from the tray, or from behind everything.

        Wanted from two directions: the tray menu, and a second copy of
        AccessCam handing over rather than starting.
        """
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        """Hide to the tray rather than quit, unless quitting was asked for.

        Ending cursor control because of a stray click on a title bar is a
        considerably worse outcome, for someone using this as their mouse, than
        a window they have to reopen. Quit lives in the tray menu, where it has
        to be chosen.
        """
        if self.quit_requested or not self.hides_to_tray:
            self.timer.stop()
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()


class _RevealFilter(QAbstractNativeEventFilter):
    """Surfaces the window when a second copy of AccessCam asks it to.

    A registered window message rather than looking the window up by title:
    titles are localised and duplicated, and the message id is guaranteed
    identical in every process that asks for the same name.
    """

    def __init__(self, reveal) -> None:
        super().__init__()
        self._reveal = reveal
        self._message = single_instance.reveal_message()
        self._last = 0.0

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt's naming
        if event_type != b"windows_generic_MSG" or not self._message:
            return False, 0

        import ctypes
        from ctypes import wintypes

        class MSG(ctypes.Structure):
            _fields_ = (
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG),
            )

        if ctypes.cast(int(message), ctypes.POINTER(MSG)).contents.message == self._message:
            # A broadcast is delivered to every top-level window this process
            # owns, not once to the process, so one request arrives several
            # times. Revealing twice is harmless; saying so twice in the log is
            # the kind of noise that makes a log worth less.
            now = time.monotonic()
            if now - self._last > _REVEAL_DEBOUNCE:
                self._last = now
                log.info("a second copy asked for the window - revealing it")
                self._reveal()

        # Never consume it. Other applications register their own messages and
        # a broadcast passes through every top-level window on the desktop.
        return False, 0


def launch(
    config: Config,
    config_file: Path | None = None,
    dry_run: bool = False,
    wait_for_camera: float = 0.0,
) -> int:
    """Open the settings window with a live engine behind it."""
    from accesscam.app import build_camera
    from accesscam.camera import CameraError
    from accesscam.hotkeys import create_listener, parse_hotkey
    from accesscam.mouse import CursorController, create_backend
    from accesscam.mouse.fake import RecordingMouse
    from accesscam.ui.first_run import choose_camera

    # Before anything else, including Qt. A second copy has nothing useful to
    # do and every reason to get out of the way quickly - the first copy holds
    # the camera, and starting a Qt application only to exit is time the user
    # spends watching nothing happen.
    instance = single_instance.claim()
    if instance is None:
        log.info("AccessCam is already running - handing it the foreground")
        single_instance.reveal_running_instance()
        return 0

    # Before QApplication: creating the Windows backend is what makes the
    # process per-monitor DPI aware, and Qt adopts that rather than imposing
    # its own if it is already set. The other order leaves the two disagreeing
    # about what a pixel is, on a desktop that really is mixed-DPI.
    #
    # It is also the only work that happens with no way to report a failure, so
    # each step says in the log that it got that far.
    log.info("creating the cursor backend")
    backend = RecordingMouse() if dry_run else create_backend()
    cursor = CursorController(backend, clutch=config.clutch)
    log.info("desktop is %s", cursor.bounds)

    # QApplication before the camera, so that failing to find one can be *said*
    # rather than only returned. Started from the logon task there is no console
    # attached and nobody sees a non-zero exit: the symptom is simply that the
    # tray icon never appears, with nothing anywhere to explain why.
    app = QApplication(sys.argv)
    log.info("Qt is up")

    try:
        camera = build_camera(config, wait=wait_for_camera)
    except CameraError as exc:
        # Not a failure to report and exit on. The stored index is simply wrong
        # for this machine more often than not on a first run, and the answer -
        # a list of what is actually connected - is a dialog away.
        log.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        camera = choose_camera(config, config_file)
        if camera is None:
            log.info("no camera chosen - exiting")
            return 1

    engine = Engine(config, camera, cursor)
    window = MainWindow(engine, config, config_file)
    log.info("window built")

    reveal_filter = _RevealFilter(window.reveal)
    app.installNativeEventFilter(reveal_filter)
    single_instance.accept_reveal_from_lesser_processes(int(window.winId()))

    # The camera's patience governs the tray's as well. Both are waiting for
    # the same thing - a machine that has only just finished logging in - and a
    # second flag saying the same thing in different words would only ever be
    # set to the same number.
    _install_tray(app, window, engine, config, config_file, wait=wait_for_camera)
    if not config.start_minimized:
        window.show()

    listener = None
    try:
        listener = create_listener(parse_hotkey(config.hotkey), engine.pause.toggle)
        listener.start()
        log.info("pause hotkey %r registered", config.hotkey)
    except Exception as exc:  # noqa: BLE001 - visible, but not fatal with a window
        log.warning("hotkey %r unavailable: %s", config.hotkey, exc)
        window.statusBar().showMessage(f"Hotkey {config.hotkey!r} unavailable: {exc}")

    engine.start()
    log.info("running")
    try:
        return app.exec()
    finally:
        log.info("shutting down")
        engine.stop()
        if listener is not None:
            listener.stop()
        camera.close()
        instance.release()


def _install_tray(
    app: QApplication,
    window: MainWindow,
    engine: Engine,
    config: Config,
    config_file: Path | None,
    wait: float = 0.0,
) -> None:
    """Put AccessCam in the tray, waiting for one to exist if need be.

    The same race the camera loses, lost against a different device. The logon
    trigger fires the moment the desktop appears - one second after the logon
    notification, in the run that prompted this - and Explorer has not yet
    created the taskbar, so `isSystemTrayAvailable` is False for a camera that
    is perfectly healthy and a shell that is seconds away. Asking once meant no
    tray icon for the rest of the session.

    So it keeps asking. It also keeps asking after Explorer *crashes*, which
    happened four minutes into that same boot, since the notification area is
    rebuilt from scratch when the shell restarts.
    """
    if _attach_tray(app, window, engine, config, config_file):
        return

    log.warning("no system tray yet - waiting up to %.0fs for the shell", wait)

    deadline = time.monotonic() + wait
    timer = QTimer(window)
    timer.setInterval(int(_TRAY_RETRY_INTERVAL * 1000))

    def retry() -> None:
        if _attach_tray(app, window, engine, config, config_file):
            timer.stop()
            return
        if time.monotonic() < deadline:
            return
        timer.stop()
        log.error("no system tray appeared - showing the window instead")
        # Never leave the app with neither a tray icon nor a window: that is
        # a process the user can see no trace of and cannot quit.
        window.show()

    timer.timeout.connect(retry)
    timer.start()


def _attach_tray(
    app: QApplication,
    window: MainWindow,
    engine: Engine,
    config: Config,
    config_file: Path | None,
) -> bool:
    """Build the tray icon if this desktop has a tray. Says whether it did."""
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return False

    def quit_now() -> None:
        window.quit_requested = True
        app.quit()

    def remember_minimised(checked: bool) -> None:
        config.start_minimized = checked
        # A failure here is not worth interrupting for: the setting still
        # applies to this run, and the window's own Save reports properly.
        with contextlib.suppress(OSError):
            config.save(config_file)

    tray = Tray(
        window=window,
        on_toggle_pause=engine.pause.toggle,
        on_quit=quit_now,
        on_start_minimised=remember_minimised,
        start_minimised=config.start_minimized,
        parent=window,
    )
    tray.show()

    window.tray = tray
    window.hides_to_tray = True
    # Hiding the window must not end the process now that there is somewhere to
    # hide to. Quit is the tray menu's job.
    app.setQuitOnLastWindowClosed(False)
    log.info("tray icon shown")
    return True

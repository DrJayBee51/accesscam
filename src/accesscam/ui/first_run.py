"""The way in when the configured camera will not open.

Until now this was a dead end: `launch` reported "Could not open camera device
0" and exited. On the machine it was developed on that is nearly always right -
the index is in the config and the camera is on the desk. On a machine that has
never run AccessCam it is nearly always *wrong*. `device` defaults to 0, a
laptop's built-in webcam habitually takes 0, and the Arducam turns up at 1 or
later. So a first run ends at a dialog with an OK button and no way past it,
which for an application whose entire job is to give someone a working pointer
is the worst possible first impression.

The camera picker already existed - in the Application tab, behind a successful
start. This puts the same choice in front of one.

Everything here has to work without a mouse. The person opening this dialog
does not have a working pointer yet; that is what they are trying to install.
So the list takes focus, Enter accepts, and every button is reachable by Tab -
the same reasoning that made the pause hotkey a bare F9 rather than a chord.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from accesscam.config import Config
from accesscam.log import log

# Long enough for the dialog to paint before the probe blocks the thread.
_PAINT_DELAY_MS = 50

# The list grows with what was found, between these. Eight indices is all
# `probe_devices` looks at, and nobody has eight cameras.
_MIN_VISIBLE_ROWS = 3
_MAX_VISIBLE_ROWS = 6


class CameraPicker(QDialog):
    """Offers whatever cameras answer, and opens the one chosen."""

    def __init__(self, config: Config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.camera = None
        self.device: int | None = None

        self.setWindowTitle("Choose a camera")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        headline = QLabel(f"AccessCam could not open camera {config.device}.")
        headline.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(headline)

        explanation = QLabel(
            "Camera numbers differ from machine to machine, and a built-in "
            "webcam usually takes 0. Pick the one AccessCam should watch — the "
            "IR camera is the one that offers 1920x1080.\n\n"
            "If it is not listed, plug it in and scan again."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        self.devices = QListWidget()
        self.devices.itemDoubleClicked.connect(self._use)
        layout.addWidget(self.devices)

        self.note = QLabel("Scanning…")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)

        buttons = QDialogButtonBox()
        self.use_button = QPushButton("Use this camera")
        self.use_button.setDefault(True)
        self.scan_button = QPushButton("Scan again")
        quit_button = QPushButton("Quit")
        buttons.addButton(self.use_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(self.scan_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(quit_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.use_button.clicked.connect(self._use)
        self.scan_button.clicked.connect(self.scan)
        quit_button.clicked.connect(self.reject)
        layout.addWidget(buttons)

        # Scanning opens every index in turn and takes seconds. Deferring it
        # until after the first paint is the difference between a dialog that
        # says "Scanning…" and a grey rectangle that looks like a hang.
        QTimer.singleShot(_PAINT_DELAY_MS, self.scan)

    # -- scanning ----------------------------------------------------------

    def scan(self) -> None:
        """Probe every index and list what answers."""
        from accesscam.camera import probe_devices

        self.note.setText("Scanning…")
        self._set_busy(True)
        QApplication.processEvents()

        try:
            found = probe_devices()
        finally:
            self._set_busy(False)

        log.info("camera picker found %d device(s)", len(found))

        self.devices.clear()
        for device in found:
            item = QListWidgetItem(device.label)
            item.setData(Qt.ItemDataRole.UserRole, device.index)
            self.devices.addItem(item)

        if not found:
            self.note.setText("No cameras answered. Check the USB connection, then scan again.")
            self.use_button.setEnabled(False)
            self._fit_list(0)
            self.scan_button.setFocus()
            return

        self.use_button.setEnabled(True)
        self.note.setText(
            f"Found {len(found)} camera{'s' if len(found) != 1 else ''}. "
            "Choose one and press Enter."
        )
        self._fit_list(len(found))
        self._preselect(found)
        # Focus goes to the list, not to a button: this dialog is operated from
        # the keyboard by someone whose pointer does not work yet.
        self.devices.setFocus()

    def _fit_list(self, count: int) -> None:
        """Give the list the height its rows need, not a fixed box of air.

        Two cameras in a ten-row well reads as a list that failed to load,
        which is the wrong impression for the one dialog a new user meets.
        """
        rows = max(min(count, _MAX_VISIBLE_ROWS), _MIN_VISIBLE_ROWS)
        row_height = self.devices.sizeHintForRow(0) if count else self.fontMetrics().height() + 8
        self.devices.setFixedHeight(rows * row_height + 2 * self.devices.frameWidth())
        self.adjustSize()

    def _preselect(self, found) -> None:
        """Start on the likeliest camera rather than on whatever came first."""
        for row, device in enumerate(found):
            if device.likely_arducam:
                self.devices.setCurrentRow(row)
                return
        self.devices.setCurrentRow(0)

    def _set_busy(self, busy: bool) -> None:
        self.use_button.setEnabled(not busy)
        self.scan_button.setEnabled(not busy)

    # -- choosing ----------------------------------------------------------

    def _use(self) -> None:
        """Open the selected camera, and only close if it really opened."""
        from accesscam.app import build_camera
        from accesscam.camera import CameraError

        item = self.devices.currentItem()
        if item is None:
            return

        device = item.data(Qt.ItemDataRole.UserRole)
        self.note.setText(f"Opening camera {device}…")
        self._set_busy(True)
        QApplication.processEvents()

        try:
            camera = build_camera(replace(self.config, device=device))
        except CameraError as exc:
            # Staying open matters: probing releases each camera it opens, but
            # something else on the machine may hold one, and the answer to
            # that is to pick a different one rather than to start over.
            log.warning("camera %s would not open from the picker: %s", device, exc)
            self.note.setText(f"Camera {device} would not open. Try another, or scan again.")
            self._set_busy(False)
            return

        log.info("camera %s chosen from the picker", device)
        self.camera = camera
        self.device = device
        self.accept()


def choose_camera(config: Config, config_file: Path | None = None):
    """Ask which camera to use, and remember the answer. None if they quit.

    The choice is saved, because the alternative is answering this dialog at
    every launch - and the whole reason it appears is that the stored index was
    wrong for this machine.
    """
    picker = CameraPicker(config)
    if picker.exec() != QDialog.DialogCode.Accepted or picker.camera is None:
        return None

    config.device = picker.device
    try:
        config.save(config_file)
    except OSError as exc:
        # Not worth refusing to start over. The camera is open and working;
        # the only cost is being asked again next time.
        log.warning("could not save the chosen camera: %s", exc)

    return picker.camera

"""System tray presence.

The icon is drawn rather than shipped, so it can carry state: green while the
cursor is being driven, red while it is parked. That is the whole reason for
putting one there. Once the window is hidden the tray is the only thing left
saying whether AccessCam currently has the pointer, and "is this thing on"
is the question a head-tracking mouse raises most often.

Closing the window hides it here rather than quitting. Quitting from a stray
click on a title bar would end cursor control outright, which for someone using
this as their mouse is a considerably worse outcome than a window they have to
reopen.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

ACTIVE = QColor(90, 200, 120)
PAUSED = QColor(220, 90, 80)
RING = QColor(232, 234, 240)

ICON_PX = 64  # drawn large and scaled down, so it stays sharp on any DPI


def marker_icon(colour: QColor) -> QIcon:
    """The tracked marker as the tray glyph: a ring with a dot at its centre.

    The same shape the preview draws over the tracked point, so the tray and
    the window are visibly talking about the same thing.
    """
    pixmap = QPixmap(ICON_PX, ICON_PX)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    centre = QPoint(ICON_PX // 2, ICON_PX // 2)
    painter.setPen(QPen(RING, 6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(centre, 24, 24)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(centre, 13, 13)
    painter.end()

    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    """Tray icon, menu, and the window's route back from being hidden."""

    def __init__(
        self,
        window: QWidget,
        on_toggle_pause: Callable[[], object],
        on_quit: Callable[[], object],
        on_start_minimised: Callable[[bool], object],
        start_minimised: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._paused: bool | None = None

        self.settings_action = QAction("Settings…", self)
        self.settings_action.triggered.connect(self.reveal)

        self.pause_action = QAction("Take control  (F9)", self)
        self.pause_action.triggered.connect(on_toggle_pause)

        self.minimised_action = QAction("Start minimised", self)
        self.minimised_action.setCheckable(True)
        self.minimised_action.setChecked(start_minimised)
        self.minimised_action.toggled.connect(on_start_minimised)

        quit_action = QAction("Quit AccessCam", self)
        quit_action.triggered.connect(on_quit)

        menu = QMenu()
        menu.addAction(self.settings_action)
        menu.addSeparator()
        menu.addAction(self.pause_action)
        menu.addSeparator()
        menu.addAction(self.minimised_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        self.set_paused(True)

    # -- state -------------------------------------------------------------

    def set_paused(self, paused: bool) -> None:
        """Recolour the icon and relabel the menu. Cheap enough to call often."""
        if paused == self._paused:
            return
        self._paused = paused
        self.setIcon(marker_icon(PAUSED if paused else ACTIVE))
        self.setToolTip(
            "AccessCam — cursor parked (F9 to take control)"
            if paused
            else "AccessCam — driving the cursor (F9 to park it)"
        )
        self.pause_action.setText("Take control  (F9)" if paused else "Park the cursor  (F9)")

    def reveal(self) -> None:
        """Bring the settings window back, wherever it went."""
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    # -- internals ---------------------------------------------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # A left click reveals rather than toggles. Toggling would hide the
        # window on the second of an accidental double click, which is easy to
        # produce with a head-tracked cursor and looks like a crash.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.reveal()

    def geometry_hint(self) -> QRect:
        return self.geometry()

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

from accesscam.assets import asset

ACTIVE = QColor(90, 200, 120)
PAUSED = QColor(220, 90, 80)
RING = QColor(232, 234, 240)

ICON_PX = 64  # drawn large and scaled down, so it stays sharp on any DPI

# Every dimension as a fraction of the canvas, so the same glyph can be drawn
# at 16px for a tray and at 256px for an application icon without redrawing it.
_RING_RADIUS = 0.375
_RING_WIDTH = 0.09375
_DOT_RADIUS = 0.203125


def marker_pixmap(colour: QColor, size: int = ICON_PX) -> QPixmap:
    """The tracked marker: a ring with a dot at its centre, at any size."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    centre = QPoint(size // 2, size // 2)
    ring = round(size * _RING_RADIUS)
    painter.setPen(QPen(RING, round(size * _RING_WIDTH)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(centre, ring, ring)

    dot = round(size * _DOT_RADIUS)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    painter.drawEllipse(centre, dot, dot)
    painter.end()

    return pixmap


# Hand-drawn artwork, if any has been supplied. Two files rather than one: the
# tray icon has to say whether the cursor is being driven, and that is the whole
# reason for putting one there. Absent, the glyph below is drawn instead.
TRAY_ART = {
    "active": "tray-active.png",
    "parked": "tray-paused.png",
    "trouble": "tray-trouble.png",
}
APP_ICON = "accesscam.ico"

TROUBLE = QColor(226, 76, 68)

_TOOLTIPS = {
    "active": "AccessCam — driving the cursor (F9 to park it)",
    "parked": "AccessCam — cursor parked (F9 to take control)",
}


def marker_icon(colour: QColor) -> QIcon:
    """The tray glyph.

    The same shape the preview draws over the tracked point, so the tray and
    the window are visibly talking about the same thing.
    """
    return QIcon(marker_pixmap(colour))


def drawn_state_icon(state: str) -> QIcon:
    """The stand-in glyph for one state.

    Deliberately distinguishable without colour: the dot is present, absent, or
    struck through. Red against green is the least legible pair for the
    commonest colour blindness, and this is an accessibility tool.
    """
    if state == "trouble":
        return QIcon(_struck_pixmap())
    if state == "parked":
        return QIcon(_ring_only_pixmap())
    return marker_icon(ACTIVE)


def tray_icon(state: str) -> QIcon:
    """The tray icon for this state: supplied artwork if present, else drawn."""
    art = asset(TRAY_ART.get(state, TRAY_ART["parked"]))
    if art is not None:
        icon = QIcon(str(art))
        if not icon.isNull():
            return icon
    return drawn_state_icon(state)


def _ring_only_pixmap(size: int = ICON_PX) -> QPixmap:
    """Parked: the ring with no marker in it - nothing is being tracked."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    centre = QPoint(size // 2, size // 2)
    ring = round(size * _RING_RADIUS)
    painter.setPen(QPen(RING, round(size * _RING_WIDTH)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(centre, ring, ring)
    painter.end()
    return pixmap


def _struck_pixmap(size: int = ICON_PX) -> QPixmap:
    """Trouble: the marker struck through, so the state survives in greyscale."""
    pixmap = marker_pixmap(TROUBLE, size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(TROUBLE, round(size * _RING_WIDTH)))
    inset = round(size * 0.18)
    painter.drawLine(inset, inset, size - inset, size - inset)
    painter.drawLine(size - inset, inset, inset, size - inset)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """The window, taskbar and Alt-Tab icon.

    Falls back to the drawn glyph so a source checkout with no `assets/` still
    shows something of its own rather than a generic interpreter icon.
    """
    art = asset(APP_ICON)
    if art is not None:
        icon = QIcon(str(art))
        if not icon.isNull():
            return icon

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(marker_pixmap(ACTIVE, size))
    return icon


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
        self._state: tuple[str, str] | None = None

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
        self.set_state("parked")

    # -- state -------------------------------------------------------------

    def set_state(self, state: str, detail: str = "") -> None:
        """Show one of driving, parked, or in trouble. Cheap to call often.

        `detail` is the trouble's explanation, and goes in the tooltip - which
        is the one place it can be read without the cursor working, since
        hovering is exactly what may have stopped.
        """
        if (state, detail) == self._state:
            return
        self._state = (state, detail)

        self.setIcon(tray_icon(state))
        if state == "trouble":
            self.setToolTip(f"AccessCam — {detail}")
        else:
            # A note rather than a warning. Not seeing the marker is ordinary -
            # you left the desk - so it belongs in the text nobody reads unless
            # they are already asking, and not on the icon everybody sees.
            self.setToolTip(_TOOLTIPS[state] + (f"\n{detail}" if detail else ""))
        paused = state != "active"
        self.pause_action.setText("Take control  (F9)" if paused else "Park the cursor  (F9)")

    def set_paused(self, paused: bool) -> None:
        """Two-state shorthand, for callers with nothing to say about health."""
        self.set_state("parked" if paused else "active")

    def reveal(self) -> None:
        """Bring the settings window back, wherever it went."""
        self._window.reveal()

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

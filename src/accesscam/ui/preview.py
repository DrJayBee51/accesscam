"""Live camera preview with the tracker's own view drawn over it.

The overlay is the point, not the picture. What matters when the marker is not
being found is *why*: whether the blob is being seen at all, whether it is
inside the region of interest, and where the tracker thinks it is. A bare video
feed would show none of that.

The region is also *editable* here, by dragging a box on the image. It is the
one setting where dragging genuinely beats stepping a number, because the value
is a place rather than a quantity - reading pixel coordinates off a picture and
typing them in is the job the picture should be doing.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

MARKER = QColor(90, 200, 120)
MARKER_LOST = QColor(220, 90, 80)
ROI_COLOUR = QColor(90, 160, 235)
ROI_DRAFT = QColor(150, 200, 255)
HANDLE_FILL = QColor(150, 200, 255)
HANDLE_EDGE = QColor(20, 24, 30)
OUTSIDE = QColor(0, 0, 0, 110)

# The smallest region that can be dragged, in frame pixels. A box smaller than
# this cannot contain the marker, so collapsing one corner onto another would
# stop tracking dead with no visible cause. The floor is not a substitute for
# the reset button - it just stops a slipped grab from being destructive.
MIN_REGION_PX = 32

# Handles are drawn smaller than they can be grabbed. Making the target larger
# than the mark is worth a great deal to someone aiming with their head, and
# costs nothing to someone aiming with a mouse.
HANDLE_DRAW = 6
HANDLE_GRAB = 16

# How far the arrow keys move the box, as a fraction of a step. The keyboard
# path exists because dragging is the hardest gesture available to a
# head-tracked cursor, and a region that can only be set by dragging would be
# unreachable exactly when tracking is misbehaving.
NUDGE_PX = 5
NUDGE_FINE_PX = 1


class PreviewWidget(QWidget):
    """Draws the latest frame, scaled to fit, with the tracked point marked."""

    roiChanged = Signal(int, int, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)  # so corners can respond to hover
        self._image: QImage | None = None
        self._frame_size = (640, 480)
        self._position: tuple[float, float] | None = None
        self._tracking = False
        self._roi: tuple[int, int, int, int] | None = None
        # Drag state. `_mode` is None, "new", "move", or a corner index 0-3
        # ordered top-left, top-right, bottom-left, bottom-right.
        self._mode: str | int | None = None
        self._anchor: tuple[int, int] | None = None
        self._grab_offset: tuple[int, int] = (0, 0)
        self._hover_corner: int | None = None

    def update_frame(
        self,
        frame: np.ndarray | None,
        position: tuple[float, float] | None,
        tracking: bool,
        roi: tuple[int, int, int, int] | None,
    ) -> None:
        if frame is not None:
            height, width = frame.shape[:2]
            self._frame_size = (width, height)
            # copy() because the QImage would otherwise reference the numpy
            # buffer, which the next frame is free to reuse under our feet.
            self._image = QImage(
                frame.data, width, height, frame.strides[0], QImage.Format.Format_BGR888
            ).copy()
        self._position = position
        self._tracking = tracking
        self._roi = roi
        self.update()

    # -- painting ----------------------------------------------------------

    def _fit(self) -> QRectF:
        """The rectangle the frame occupies, letterboxed to preserve aspect."""
        width, height = self._frame_size
        if width <= 0 or height <= 0:
            return QRectF(self.rect())
        scale = min(self.width() / width, self.height() / height)
        drawn_w, drawn_h = width * scale, height * scale
        return QRectF((self.width() - drawn_w) / 2, (self.height() - drawn_h) / 2, drawn_w, drawn_h)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(18, 18, 20))

        if self._image is None:
            painter.setPen(QColor(150, 150, 155))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "waiting for the camera…")
            return

        target = self._fit()
        painter.drawImage(target, self._image)

        width, height = self._frame_size
        scale_x = target.width() / width
        scale_y = target.height() / height

        if self._roi is not None:
            x, y, w, h = self._roi
            box = QRectF(
                target.left() + x * scale_x,
                target.top() + y * scale_y,
                w * scale_x,
                h * scale_y,
            )
            # Dim what the tracker is ignoring. A box outline alone leaves it
            # ambiguous which side of the line is the excluded one.
            if box != target:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(OUTSIDE)
                for band in (
                    QRectF(target.left(), target.top(), target.width(), box.top() - target.top()),
                    QRectF(
                        target.left(), box.bottom(), target.width(), target.bottom() - box.bottom()
                    ),
                    QRectF(target.left(), box.top(), box.left() - target.left(), box.height()),
                    QRectF(box.right(), box.top(), target.right() - box.right(), box.height()),
                ):
                    if band.width() > 0 and band.height() > 0:
                        painter.drawRect(band)

            active = self._mode is not None
            painter.setPen(
                QPen(ROI_DRAFT if active else ROI_COLOUR, 2, Qt.PenStyle.SolidLine)
                if active
                else QPen(ROI_COLOUR, 2, Qt.PenStyle.DashLine)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(box)

            # Corner handles. Drawn last so they sit above the outline, and
            # enlarged on hover so it is obvious which one is about to be taken.
            for index, corner in enumerate(
                (box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight())
            ):
                lit = index == self._hover_corner or index == self._mode
                size = HANDLE_DRAW + (2 if lit else 0)
                painter.setPen(QPen(HANDLE_EDGE, 1))
                painter.setBrush(HANDLE_FILL if lit else ROI_COLOUR)
                painter.drawRect(QRectF(corner.x() - size, corner.y() - size, size * 2, size * 2))

        if self._position is not None:
            colour = MARKER if self._tracking else MARKER_LOST
            centre = QPointF(
                target.left() + self._position[0] * scale_x,
                target.top() + self._position[1] * scale_y,
            )
            painter.setPen(QPen(colour, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, 13, 13)
            # Crosshair through the centre: at this scale a circle alone is not
            # precise enough to judge whether the centroid is actually centred.
            painter.drawLine(
                QPointF(centre.x() - 20, centre.y()), QPointF(centre.x() - 5, centre.y())
            )
            painter.drawLine(
                QPointF(centre.x() + 5, centre.y()), QPointF(centre.x() + 20, centre.y())
            )
            painter.drawLine(
                QPointF(centre.x(), centre.y() - 20), QPointF(centre.x(), centre.y() - 5)
            )
            painter.drawLine(
                QPointF(centre.x(), centre.y() + 5), QPointF(centre.x(), centre.y() + 20)
            )

    # -- editing the region ------------------------------------------------

    def _to_frame(self, point: QPointF) -> tuple[int, int]:
        """Widget coordinates to frame pixels, clamped to the frame."""
        target = self._fit()
        width, height = self._frame_size
        x = (point.x() - target.left()) / max(target.width(), 1) * width
        y = (point.y() - target.top()) / max(target.height(), 1) * height
        return (max(0, min(int(round(x)), width - 1)), max(0, min(int(round(y)), height - 1)))

    def _box_rect(self) -> QRectF | None:
        """The region in widget coordinates."""
        if self._roi is None:
            return None
        target = self._fit()
        width, height = self._frame_size
        x, y, w, h = self._roi
        return QRectF(
            target.left() + x / width * target.width(),
            target.top() + y / height * target.height(),
            w / width * target.width(),
            h / height * target.height(),
        )

    def _corners(self) -> list[QPointF]:
        box = self._box_rect()
        if box is None:
            return []
        return [box.topLeft(), box.topRight(), box.bottomLeft(), box.bottomRight()]

    def _corner_at(self, point: QPointF) -> int | None:
        for index, corner in enumerate(self._corners()):
            if (
                abs(corner.x() - point.x()) <= HANDLE_GRAB
                and abs(corner.y() - point.y()) <= HANDLE_GRAB
            ):
                return index
        return None

    def _commit(self, x0: int, y0: int, x1: int, y1: int) -> None:
        """Publish a region from two opposite corners, in frame pixels."""
        width, height = self._frame_size
        left, right = sorted((x0, x1))
        top, bottom = sorted((y0, y1))

        # Hold the floor by pushing the moving edge back out, so a corner
        # dragged past its opposite stops rather than inverting.
        if right - left < MIN_REGION_PX:
            right = min(left + MIN_REGION_PX, width)
            left = min(left, right - MIN_REGION_PX)
        if bottom - top < MIN_REGION_PX:
            bottom = min(top + MIN_REGION_PX, height)
            top = min(top, bottom - MIN_REGION_PX)

        self._roi = (max(left, 0), max(top, 0), right - left, bottom - top)
        self.update()
        self.roiChanged.emit(*self._roi)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = event.position()
        box = self._box_rect()

        corner = self._corner_at(point)
        if corner is not None and self._roi is not None:
            # Anchor the opposite corner and drag this one against it.
            x, y, w, h = self._roi
            opposite = {0: (x + w, y + h), 1: (x, y + h), 2: (x + w, y), 3: (x, y)}[corner]
            self._mode = corner
            self._anchor = opposite
        elif box is not None and box.contains(point):
            self._mode = "move"
            frame_point = self._to_frame(point)
            self._grab_offset = (
                frame_point[0] - self._roi[0],
                frame_point[1] - self._roi[1],
            )
        # A press anywhere else does nothing. Drawing a fresh box on any stray
        # click is too easy to trigger by accident with a head-tracked cursor,
        # and losing a tuned region that way is a real cost against a
        # convenience that the handles already cover.
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        point = event.position()

        if self._mode is None:
            hover = self._corner_at(point)
            if hover != self._hover_corner:
                self._hover_corner = hover
                self.setCursor(
                    Qt.CursorShape.SizeFDiagCursor
                    if hover in (0, 3)
                    else Qt.CursorShape.SizeBDiagCursor
                    if hover in (1, 2)
                    else Qt.CursorShape.CrossCursor
                )
                self.update()
            return

        x, y = self._to_frame(point)
        if self._mode == "move" and self._roi is not None:
            width, height = self._frame_size
            _, _, w, h = self._roi
            left = max(0, min(x - self._grab_offset[0], width - w))
            top = max(0, min(y - self._grab_offset[1], height - h))
            self._commit(left, top, left + w, top + h)
        elif self._anchor is not None:
            self._commit(self._anchor[0], self._anchor[1], x, y)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        if event.button() != Qt.MouseButton.LeftButton or self._mode is None:
            return

        self._mode = None
        self._anchor = None
        self._before_drag = None
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        """Arrows move the region; with Shift they resize it from the bottom right."""
        if self._roi is None:
            super().keyPressEvent(event)
            return

        deltas = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() not in deltas:
            super().keyPressEvent(event)
            return

        modifiers = event.modifiers()
        amount = NUDGE_FINE_PX if modifiers & Qt.KeyboardModifier.ControlModifier else NUDGE_PX
        dx, dy = deltas[event.key()]
        dx, dy = dx * amount, dy * amount
        x, y, w, h = self._roi
        width, height = self._frame_size

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            self._commit(
                x, y, max(x + 1, min(x + w + dx, width)), max(y + 1, min(y + h + dy, height))
            )
        else:
            left = max(0, min(x + dx, width - w))
            top = max(0, min(y + dy, height - h))
            self._commit(left, top, left + w, top + h)

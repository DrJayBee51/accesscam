"""Live camera preview with the tracker's own view drawn over it.

The overlay is the point, not the picture. What matters when the marker is not
being found is *why*: whether the blob is being seen at all, whether it is
inside the region of interest, and where the tracker thinks it is. A bare video
feed would show none of that.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

MARKER = QColor(90, 200, 120)
MARKER_LOST = QColor(220, 90, 80)
ROI_COLOUR = QColor(90, 160, 235)


class PreviewWidget(QWidget):
    """Draws the latest frame, scaled to fit, with the tracked point marked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._image: QImage | None = None
        self._frame_size = (640, 480)
        self._position: tuple[float, float] | None = None
        self._tracking = False
        self._roi: tuple[int, int, int, int] | None = None

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
            pen = QPen(ROI_COLOUR, 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(
                QRectF(
                    target.left() + x * scale_x,
                    target.top() + y * scale_y,
                    w * scale_x,
                    h * scale_y,
                )
            )

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

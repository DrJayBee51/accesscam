"""The acceleration curve, plotted from the function the mapper actually runs.

`acceleration_scale` is imported rather than reimplemented. A plot that drew its
own version of the curve would drift from the real one the first time either
changed, and a settings display that lies is worse than no display.

A live marker shows where the marker's *current* speed sits on the curve, so
moving your head draws the answer to "which part of this am I using".
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from accesscam.mapper import acceleration_scale

CURVE = QColor(90, 160, 235)
FLAT = QColor(225, 120, 70)
LIVE = QColor(90, 200, 120)
GRID = QColor(58, 58, 64)
AXIS = QColor(110, 110, 118)
INK = QColor(228, 228, 232)
MUTED = QColor(150, 150, 158)

VMAX = 240.0  # marker px/s across the plot
MARGIN_LEFT = 54
MARGIN_RIGHT = 16
MARGIN_TOP = 14
MARGIN_BOTTOM = 34


class CurveWidget(QWidget):
    """Gain against marker speed, with the flat gain drawn for comparison."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._gain = 100.0
        self._floor = 1.0
        self._knee = 40.0
        self._sharpness = 1.8
        self._live_speed: float | None = None

    def set_curve(self, gain: float, floor: float, knee: float, sharpness: float) -> None:
        self._gain = gain
        self._floor = floor
        self._knee = knee
        self._sharpness = sharpness
        self.update()

    def set_live_speed(self, speed: float | None) -> None:
        self._live_speed = speed
        self.update()

    # -- geometry ----------------------------------------------------------

    def _plot_rect(self) -> QRectF:
        return QRectF(
            MARGIN_LEFT,
            MARGIN_TOP,
            max(self.width() - MARGIN_LEFT - MARGIN_RIGHT, 1),
            max(self.height() - MARGIN_TOP - MARGIN_BOTTOM, 1),
        )

    def _gain_max(self) -> float:
        # Rounded up to a tidy step so the axis labels stay readable as the
        # gain slider moves, rather than jittering with every tick.
        for step in (5, 10, 20, 25, 50):
            top = -(-self._gain * 1.15 // step) * step
            if top / step <= 7:
                return float(top)
        return self._gain * 1.15

    def _gain_at(self, speed: float) -> float:
        return self._gain * acceleration_scale(speed, self._floor, self._knee, self._sharpness)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot = self._plot_rect()
        gain_max = self._gain_max()

        def x_of(speed: float) -> float:
            return plot.left() + (speed / VMAX) * plot.width()

        def y_of(gain: float) -> float:
            return plot.bottom() - (gain / gain_max) * plot.height()

        small = QFont(self.font())
        small.setPointSizeF(max(self.font().pointSizeF() - 1.0, 7.0))
        painter.setFont(small)

        # Grid and vertical axis
        step = gain_max / 5
        painter.setPen(QPen(GRID, 1))
        for index in range(6):
            value = step * index
            y = y_of(value)
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(0, y - 9, MARGIN_LEFT - 8, 18),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.0f}",
            )

        painter.setPen(QPen(AXIS, 1))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        for speed in (0, 60, 120, 180, 240):
            x = x_of(speed)
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(x - 28, plot.bottom() + 4, 56, 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{speed}",
            )
        painter.drawText(
            QRectF(plot.left(), self.height() - 17, plot.width(), 16),
            Qt.AlignmentFlag.AlignCenter,
            "marker speed (px/s)",
        )

        # Flat reference
        painter.setPen(QPen(FLAT, 2, Qt.PenStyle.DashLine))
        painter.drawLine(
            QPointF(plot.left(), y_of(self._gain)), QPointF(plot.right(), y_of(self._gain))
        )

        # The curve itself
        path = QPainterPath()
        samples = max(int(plot.width()), 2)
        for index in range(samples + 1):
            speed = VMAX * index / samples
            point = QPointF(x_of(speed), y_of(self._gain_at(speed)))
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QPen(CURVE, 2))
        painter.drawPath(path)

        # Knee, only when the curve is doing something
        if self._floor < 1.0 and 0 < self._knee <= VMAX:
            x = x_of(self._knee)
            painter.setPen(QPen(CURVE, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setBrush(CURVE)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y_of(self._gain_at(self._knee))), 4, 4)

        # Where the marker is right now
        if self._live_speed is not None:
            speed = min(self._live_speed, VMAX)
            x, y = x_of(speed), y_of(self._gain_at(speed))
            painter.setPen(QPen(LIVE, 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setBrush(LIVE)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y), 5, 5)
            painter.setPen(INK)
            painter.drawText(
                QRectF(x + 8, y - 22, 96, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"{self._gain_at(speed):.0f} px/px",
            )

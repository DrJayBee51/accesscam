"""The acceleration curve, plotted from the function the mapper actually runs.

`acceleration_scale` is imported rather than reimplemented. A plot that drew its
own version of the curve would drift from the real one the first time either
changed, and a settings display that lies is worse than no display.

A live marker shows where the marker's *current* speed sits on the curve, so
moving your head draws the answer to "which part of this am I using".
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
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

# The vertical axis is a percentage of full gain, not an absolute px/px. The
# curve scales h_gain and v_gain by the same factor, so plotting either one in
# absolute terms would show a number that is only true for that axis, and would
# redraw itself every time a gain slider moved without the curve having changed
# shape at all. A little headroom above 100 keeps the full-gain line off the
# very top edge.
SMAX = 105.0
# Room for the rotated axis title at the far left, then the tick labels, both
# at the same size as the setting titles beside the plot.
MARGIN_LEFT = 68
MARGIN_RIGHT = 16
MARGIN_TOP = 16
MARGIN_BOTTOM = 46
TITLE_X = 15
TICK_LEFT = 26


class CurveWidget(QWidget):
    """Gain against marker speed, with the flat gain drawn for comparison."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._floor = 1.0
        self._knee = 40.0
        self._sharpness = 1.8
        self._live_speed: float | None = None

    def set_curve(self, floor: float, knee: float, sharpness: float) -> None:
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

    def _percent_at(self, speed: float) -> float:
        """Gain at this speed as a percentage of full gain."""
        return 100.0 * acceleration_scale(speed, self._floor, self._knee, self._sharpness)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt's naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot = self._plot_rect()

        def x_of(speed: float) -> float:
            return plot.left() + (speed / VMAX) * plot.width()

        def y_of(percent: float) -> float:
            return plot.bottom() - (percent / SMAX) * plot.height()

        # The widget's own font, unshrunk, so the plot reads at the same size as
        # the setting titles beside it rather than looking like a footnote.
        painter.setFont(self.font())

        # Grid and vertical axis
        for value in (0, 25, 50, 75, 100):
            y = y_of(value)
            painter.setPen(QPen(GRID, 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(TICK_LEFT, y - 10, MARGIN_LEFT - TICK_LEFT - 10, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{value}%",
            )

        painter.setPen(QPen(AXIS, 1))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))

        for speed in (0, 60, 120, 180, 240):
            x = x_of(speed)
            painter.setPen(MUTED)
            painter.drawText(
                QRectF(x - 30, plot.bottom() + 5, 60, 19),
                Qt.AlignmentFlag.AlignCenter,
                f"{speed}",
            )
        painter.drawText(
            QRectF(plot.left(), self.height() - 21, plot.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "marker speed (px/s)",
        )

        painter.save()
        painter.translate(TITLE_X, plot.center().y())
        painter.rotate(-90)
        painter.setPen(MUTED)
        painter.drawText(
            QRectF(-plot.height() / 2, -10, plot.height(), 20),
            Qt.AlignmentFlag.AlignCenter,
            "% of full gain",
        )
        painter.restore()

        # Full gain, the ceiling the curve approaches but never crosses.
        painter.setPen(QPen(FLAT, 2, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(plot.left(), y_of(100)), QPointF(plot.right(), y_of(100)))

        # The curve itself
        path = QPainterPath()
        samples = max(int(plot.width()), 2)
        for index in range(samples + 1):
            speed = VMAX * index / samples
            point = QPointF(x_of(speed), y_of(self._percent_at(speed)))
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
            painter.drawEllipse(QPointF(x, y_of(self._percent_at(self._knee))), 4, 4)

        # Where the marker is right now
        if self._live_speed is not None:
            speed = min(self._live_speed, VMAX)
            x, y = x_of(speed), y_of(self._percent_at(speed))
            painter.setPen(QPen(LIVE, 1, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setBrush(LIVE)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(x, y), 5, 5)
            # Flip the readout to the left of the line when it would otherwise
            # run off the plot, which it always did at full speed - the one
            # place the number is most worth reading.
            label = QRectF(x + 8, y - 22, 70, 16)
            align = Qt.AlignmentFlag.AlignLeft
            if label.right() > plot.right():
                label = QRectF(x - 78, y - 22, 70, 16)
                align = Qt.AlignmentFlag.AlignRight
            painter.setPen(INK)
            painter.drawText(
                label,
                align | Qt.AlignmentFlag.AlignVCenter,
                f"{self._percent_at(speed):.0f}%",
            )

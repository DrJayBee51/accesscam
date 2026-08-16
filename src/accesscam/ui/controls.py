"""A labelled numeric control, built for the input the user actually has.

A plain slider assumes dragging: press, hold, move, release. That is the single
hardest gesture for someone driving the cursor with their head and clicking
from a QuadStick, and it is exactly the gesture they would need to *fix* the
tracking that is making it hard. So every value here is reachable three ways -
the step buttons (one click each), the arrow keys once focused, and the slider
for when the pointer is behaving.

The step buttons are the important ones. They are deliberately large.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from accesscam.ui.help import HelpButton


class Tuner(QWidget):
    """One setting: a label, a live value, step buttons and a slider."""

    valueChanged = Signal(float)

    def __init__(
        self,
        label: str,
        key: str,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int = 2,
        suffix: str = "",
        help_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._min = minimum
        self._max = maximum
        self._step = step
        self._decimals = decimals
        self._suffix = suffix
        self._emitting = True

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(max(int(round((maximum - minimum) / step)), 1))
        self._slider.setSingleStep(1)
        self._slider.setPageStep(5)
        self._slider.setAccessibleName(label)

        self._value_label = QLabel()
        self._value_label.setObjectName("tunerValue")
        self._value_label.setMinimumWidth(96)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        name = QLabel(label)
        name.setObjectName("tunerName")

        heading = QHBoxLayout()
        heading.setSpacing(7)
        heading.addWidget(name)
        if help_text:
            heading.addWidget(HelpButton(help_text, label))
        heading.addStretch(1)
        heading.addWidget(self._value_label)

        self._down = QPushButton("−")
        self._up = QPushButton("+")
        for button in (self._down, self._up):
            button.setObjectName("stepButton")
            button.setFixedSize(40, 34)
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(400)
            button.setAutoRepeatInterval(90)
        self._down.setAccessibleName(f"{label} down")
        self._up.setAccessibleName(f"{label} up")

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._down)
        row.addWidget(self._slider, 1)
        row.addWidget(self._up)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(heading)
        layout.addLayout(row)

        self._slider.valueChanged.connect(self._on_slider)
        self._down.clicked.connect(lambda: self.step(-1))
        self._up.clicked.connect(lambda: self.step(+1))

    # -- value -------------------------------------------------------------

    def value(self) -> float:
        return self._min + self._slider.value() * self._step

    def set_value(self, value: float, *, emit: bool = False) -> None:
        """Move to `value`, silently by default so loading a config is not a change."""
        ticks = int(round((value - self._min) / self._step))
        ticks = max(0, min(self._slider.maximum(), ticks))
        self._emitting = emit
        try:
            self._slider.setValue(ticks)
        finally:
            self._emitting = True
        self._refresh_label()

    def step(self, direction: int) -> None:
        self._slider.setValue(self._slider.value() + direction)

    # -- internals ---------------------------------------------------------

    def _on_slider(self, _ticks: int) -> None:
        self._refresh_label()
        if self._emitting:
            self.valueChanged.emit(self.value())

    def _refresh_label(self) -> None:
        self._value_label.setText(f"{self.value():.{self._decimals}f}{self._suffix}")

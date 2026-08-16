"""Explanations behind a question mark, shown on click.

Deliberately not a hover tooltip. Qt hides those as soon as the pointer moves,
and a head-tracked pointer never stops moving - the explanation would flicker
away before it could be read. A click-to-open popup stays put until it is
dismissed, which is the only version of this that works for the person the
application is for.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QToolButton, QVBoxLayout, QWidget

POPUP_WIDTH = 300


class HelpPopup(QFrame):
    """A small panel of text that closes on the next click anywhere else."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("helpPopup")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        label = QLabel(text)
        label.setObjectName("helpText")
        label.setWordWrap(True)
        label.setFixedWidth(POPUP_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(label)

    def show_beside(self, anchor: QWidget) -> None:
        """Open just below the button, nudged left so it stays on screen."""
        origin = anchor.mapToGlobal(anchor.rect().bottomLeft())
        self.adjustSize()
        x, y = origin.x() - 8, origin.y() + 6

        screen = anchor.screen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(x, available.right() - self.width() - 8)
            x = max(x, available.left() + 8)
            if y + self.height() > available.bottom():
                y = anchor.mapToGlobal(anchor.rect().topLeft()).y() - self.height() - 6

        self.move(x, y)
        self.show()


class HelpButton(QToolButton):
    """A question mark that explains one setting."""

    def __init__(self, text: str, label: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("helpButton")
        self.setText("?")
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"What does {label} do?" if label else "Help")
        self._text = text
        self.clicked.connect(self._open)

    def _open(self) -> None:
        popup = HelpPopup(self._text, self)
        popup.setStyleSheet(self.window().styleSheet())
        popup.show_beside(self)

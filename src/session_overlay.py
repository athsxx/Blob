"""Modal wait overlay so camera handshake and ROI apply never look frozen."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class SessionBusyOverlay(QWidget):
    """Full-parent dimmer with a title, detail line, and pulsing dots."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("sessionBusyOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#sessionBusyOverlay { background-color: rgba(14, 39, 66, 90); }"
        )
        self.hide()

        card = QFrame(self)
        card.setObjectName("formCard")
        card.setFixedWidth(480)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(24, 24, 24, 24)
        inner.setSpacing(12)

        self._title = QLabel("Please wait")
        self._title.setObjectName("pageTitleMain")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setObjectName("pageHint")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._pulse = QLabel("● ● ●")
        self._pulse.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pulse.setStyleSheet("color: #810055; font-size: 16px; letter-spacing: 0.4em;")
        inner.addWidget(self._title)
        inner.addWidget(self._detail)
        inner.addWidget(self._pulse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)

        self._dots = 0
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._tick)

    def show_message(self, title: str, detail: str = "") -> None:
        self._title.setText(title)
        self._detail.setText(detail)
        self._detail.setVisible(bool(detail))
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def clear(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._dots = (self._dots + 1) % 4
        self._pulse.setText(" ".join("●" if i < self._dots else "○" for i in range(3)))
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())

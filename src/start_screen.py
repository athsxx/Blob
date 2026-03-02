"""
Start Screen — Manifold Inspection System

Landing page shown before the main dashboard.
Operator selects inspection mode:
  - Sequential Inspection (guided step-by-step)
  - Custom Inspection (disabled for POC)
"""

import sys

try:
    from PyQt6.QtWidgets import (
        QApplication, QDialog, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QFrame, QWidget
    )
    from PyQt6.QtCore import Qt, pyqtSignal
    from PyQt6.QtGui import QFont
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False

START_SCREEN_STYLESHEET = """
QDialog {
    background-color: #0d1117;
}
QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'Inter', 'SF Pro Display', 'Segoe UI', sans-serif;
}
QLabel {
    color: #e6edf3;
    background-color: transparent;
}
QFrame#divider {
    background-color: #30363d;
    max-height: 1px;
    min-height: 1px;
}
QPushButton#btnSequential {
    background-color: #238636;
    color: #ffffff;
    font-weight: bold;
    font-size: 16px;
    padding: 20px 40px;
    border: none;
    border-radius: 8px;
    min-width: 260px;
    min-height: 80px;
}
QPushButton#btnSequential:hover {
    background-color: #2ea043;
}
QPushButton#btnSequential:pressed {
    background-color: #196c2e;
}
QPushButton#btnCustom {
    background-color: #21262d;
    color: #484f58;
    font-weight: bold;
    font-size: 16px;
    padding: 20px 40px;
    border: 2px solid #30363d;
    border-radius: 8px;
    min-width: 260px;
    min-height: 80px;
}
QPushButton#btnCustom:disabled {
    background-color: #161b22;
    color: #3d444d;
    border-color: #21262d;
}
"""

# Return values from the dialog
MODE_SEQUENTIAL = "Sequential"
MODE_CUSTOM = "Custom"
MODE_CANCELLED = None


class StartScreen(QDialog):
    """
    Landing page dialog.
    Returns MODE_SEQUENTIAL or MODE_CANCELLED.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manifold Inspection System")
        self.setFixedSize(700, 520)
        self.setStyleSheet(START_SCREEN_STYLESHEET)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint
        )

        self._selected_mode = MODE_CANCELLED

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header banner ──
        header = QFrame()
        header.setStyleSheet(
            "background-color: #161b22; border-bottom: 2px solid #238636;"
        )
        header.setFixedHeight(90)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 16, 40, 16)
        header_layout.setSpacing(4)

        title_lbl = QLabel("⬡  MANIFOLD INSPECTION SYSTEM")
        title_lbl.setStyleSheet(
            "color: #f0f6fc; font-size: 22px; font-weight: bold; "
            "letter-spacing: 2px; background-color: transparent;"
        )
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle_lbl = QLabel("Select Inspection Mode")
        subtitle_lbl.setStyleSheet(
            "color: #8b949e; font-size: 13px; background-color: transparent;"
        )
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(title_lbl)
        header_layout.addWidget(subtitle_lbl)
        layout.addWidget(header)

        # ── Body ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(60, 50, 60, 50)
        body_layout.setSpacing(24)

        # Mode buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(30)

        # Sequential button + description
        seq_col = QVBoxLayout()
        seq_col.setSpacing(12)

        self.btn_sequential = QPushButton("▶  Sequential Inspection")
        self.btn_sequential.setObjectName("btnSequential")
        self.btn_sequential.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sequential.clicked.connect(self._on_sequential)

        seq_desc = QLabel(
            "Guided step-by-step inspection.\n"
            "System tells you exactly which hole\n"
            "to insert the laser into."
        )
        seq_desc.setStyleSheet(
            "color: #8b949e; font-size: 12px; "
            "background-color: transparent; line-height: 1.5;"
        )
        seq_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seq_desc.setWordWrap(True)

        seq_col.addWidget(self.btn_sequential)
        seq_col.addWidget(seq_desc)

        # Custom button + description
        cust_col = QVBoxLayout()
        cust_col.setSpacing(12)

        self.btn_custom = QPushButton("⚙  Custom Inspection")
        self.btn_custom.setObjectName("btnCustom")
        self.btn_custom.setEnabled(False)

        cust_desc = QLabel(
            "Define your own inspection order.\n"
            "Select specific holes and rules\n"
            "to test manually.\n\n"
            "[ Coming Soon ]"
        )
        cust_desc.setStyleSheet(
            "color: #3d444d; font-size: 12px; "
            "background-color: transparent; line-height: 1.5;"
        )
        cust_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cust_desc.setWordWrap(True)

        cust_col.addWidget(self.btn_custom)
        cust_col.addWidget(cust_desc)

        btn_row.addLayout(seq_col)
        btn_row.addLayout(cust_col)
        body_layout.addLayout(btn_row)

        # Divider
        div = QFrame()
        div.setObjectName("divider")
        body_layout.addWidget(div)

        # Info row at bottom
        info_lbl = QLabel(
            "Active Cameras: Face A · Face B · Face C · Face D · Face E   |   "
            "Face F: Not Available (POC)"
        )
        info_lbl.setStyleSheet(
            "color: #484f58; font-size: 11px; background-color: transparent;"
        )
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(info_lbl)

        layout.addWidget(body, stretch=1)

        # ── Footer ──
        footer = QFrame()
        footer.setStyleSheet(
            "background-color: #161b22; border-top: 1px solid #21262d;"
        )
        footer.setFixedHeight(36)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)

        ver_lbl = QLabel("POC v1.0  —  GnB Plant 8")
        ver_lbl.setStyleSheet("color: #3d444d; font-size: 11px; background-color: transparent;")
        footer_layout.addWidget(ver_lbl)
        footer_layout.addStretch()

        layout.addWidget(footer)

    def _on_sequential(self):
        self._selected_mode = MODE_SEQUENTIAL
        self.accept()

    def get_mode(self) -> str:
        """Return the selected mode string, or MODE_CANCELLED."""
        return self._selected_mode


def show_start_screen() -> str:
    """
    Show the start screen dialog and return the selected mode.
    Returns MODE_SEQUENTIAL or MODE_CANCELLED.
    """
    if not HAS_PYQT6:
        print("[StartScreen] PyQt6 not available — defaulting to sequential mode")
        return MODE_SEQUENTIAL

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    screen = StartScreen()
    result = screen.exec()

    if result == QDialog.DialogCode.Accepted:
        return screen.get_mode()
    return MODE_CANCELLED


if __name__ == "__main__":
    mode = show_start_screen()
    print(f"Selected mode: {mode}")

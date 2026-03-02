"""
Operator Dashboard — PyQt6  (Guided Inspection Mode)

3-column layout:
  ┌──────────────────────────────────────────────────────────────┐
  │  ⬡ MANIFOLD INSPECTION SYSTEM          ● STOPPED   17:00:00 │
  │  [START]  [STOP]  [PAUSE]  [RESUME]  [OVERRIDE]             │
  ├──────────────┬──────────────────────────┬────────────────────┤
  │ STEP LIST    │  INSTRUCTION PANEL       │  CAMERAS           │
  │  01. A·H1    │  Step 1 of 65            │  [A] [B] [C]       │
  │ ▶02. A·H2    │  INSERT LASER INTO:      │  [D] [E]           │
  │  03. B·H1    │    Face A / H2           │                    │
  │  ...         │  EXPECT LIGHT AT:        │                    │
  │              │    Face C → H5           │                    │
  │              │  ⏸ WAITING               │                    │
  ├──────────────┴──────────────────────────┴────────────────────┤
  │  Progress: 1 / 65 steps  [████░░░░░░░░░░░░░░░░░░]           │
  └──────────────────────────────────────────────────────────────┘
"""

import sys
import time
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout,
        QHBoxLayout, QGridLayout, QFrame, QProgressBar, QScrollArea,
        QSizePolicy, QPushButton, QDialog, QComboBox, QRadioButton,
        QButtonGroup, QDialogButtonBox, QStackedWidget
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QImage, QPixmap, QFont, QColor, QPalette
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False
    print("[Dashboard] PyQt6 not installed. Install with: pip install PyQt6")


# ──────────────────────────────────────────────
# STYLESHEET
# ──────────────────────────────────────────────

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'SF Pro Display', 'Segoe UI', sans-serif;
}
QLabel { color: #e6edf3; }

/* Header */
QFrame#headerBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
}
QLabel#headerTitle {
    color: #f0f6fc;
    font-size: 15px;
    font-weight: bold;
}
QLabel#headerClock { color: #8b949e; font-size: 13px; }
QLabel#headerStatus {
    font-size: 12px;
    font-weight: bold;
    padding: 3px 10px;
    border-radius: 4px;
}

/* Control bar */
QFrame#controlBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
}
QPushButton#btnStart {
    background-color: #238636; color: #fff; font-weight: bold;
    font-size: 12px; padding: 5px 14px; border: none; border-radius: 4px;
}
QPushButton#btnStart:hover  { background-color: #2ea043; }
QPushButton#btnStart:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnStop {
    background-color: #da3633; color: #fff; font-weight: bold;
    font-size: 12px; padding: 5px 14px; border: none; border-radius: 4px;
}
QPushButton#btnStop:hover  { background-color: #f85149; }
QPushButton#btnStop:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnPause {
    background-color: #9e6a03; color: #fff; font-weight: bold;
    font-size: 12px; padding: 5px 14px; border: none; border-radius: 4px;
}
QPushButton#btnPause:hover  { background-color: #bb8009; }
QPushButton#btnPause:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnResume {
    background-color: #1f6feb; color: #fff; font-weight: bold;
    font-size: 12px; padding: 5px 14px; border: none; border-radius: 4px;
}
QPushButton#btnResume:hover  { background-color: #388bfd; }
QPushButton#btnResume:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnOverride {
    background-color: #6e40c9; color: #fff; font-weight: bold;
    font-size: 12px; padding: 5px 14px; border: none; border-radius: 4px;
}
QPushButton#btnOverride:hover  { background-color: #8957e5; }
QPushButton#btnOverride:disabled { background-color: #21262d; color: #484f58; }

/* Camera cell */
QFrame#cameraCell {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 5px;
}

/* Step list */
QFrame#stepListPanel {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
}

/* Instruction panel */
QFrame#instructionPanel {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 6px;
}

/* Progress bar */
QProgressBar {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    text-align: center;
    color: #e6edf3;
    font-weight: bold;
    height: 20px;
}
QProgressBar::chunk { background-color: #238636; border-radius: 3px; }

/* Override dialog */
QDialog { background-color: #161b22; color: #e6edf3; }
QComboBox {
    background-color: #21262d; color: #e6edf3;
    border: 1px solid #30363d; border-radius: 4px;
    padding: 5px 8px; font-size: 13px;
}
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #21262d; color: #e6edf3;
    selection-background-color: #388bfd;
}
QRadioButton { color: #e6edf3; font-size: 13px; spacing: 8px; }

/* Scrollbar */
QScrollBar:vertical {
    background: #0d1117; width: 8px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #30363d; border-radius: 4px; min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


# ──────────────────────────────────────────────
# CameraWidget
# ──────────────────────────────────────────────

class CameraWidget(QFrame):
    """Single camera feed cell."""

    def __init__(self, face: str, usb_index: Optional[int] = None, parent=None):
        super().__init__(parent)
        self.face = face
        self.setObjectName("cameraCell")
        self.setMinimumSize(160, 120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.feed_label = QLabel()
        self.feed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        label_text = f"Index {usb_index} | Face {face}" if usb_index is not None else f"Face {face}"
        self.feed_label.setText(f"{label_text}\nNO SIGNAL")
        self.feed_label.setStyleSheet(
            "background-color: #0d1117; border-radius: 5px; "
            "color: #484f58; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.feed_label)

        # Overlays
        self._face_lbl = QLabel(label_text, self)
        self._face_lbl.setStyleSheet(
            "background-color: rgba(13,17,23,180); color: #58a6ff; "
            "font-weight: bold; font-size: 11px; padding: 4px 8px; border-radius: 3px;"
        )
        self._face_lbl.adjustSize()
        self._face_lbl.move(6, 6)

        self._fps_lbl = QLabel("-- fps", self)
        self._fps_lbl.setStyleSheet(
            "background-color: rgba(13,17,23,160); color: #8b949e; "
            "font-size: 10px; padding: 3px 6px; border-radius: 3px;"
        )
        self._fps_lbl.adjustSize()
        self._fps_lbl.move(6, 6 + self._face_lbl.height() + 4)

    def update_frame(self, frame: np.ndarray):
        w = self.feed_label.width()
        h = self.feed_label.height()
        if w < 10 or h < 10:
            return
        rgb = frame[..., ::-1].copy()
        fh, fw = rgb.shape[:2]
        qimg = QImage(rgb.data, fw, fh, 3 * fw, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.feed_label.setPixmap(scaled)
        self.feed_label.setStyleSheet("background-color: #0d1117; border-radius: 5px;")

    def update_stats(self, fps: float, det_count: int):
        self._fps_lbl.setText(f"{fps:.1f} fps")
        self._fps_lbl.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._face_lbl.move(6, 6)
        self._fps_lbl.move(6, 6 + self._face_lbl.height() + 4)


# ──────────────────────────────────────────────
# StepListPanel  (left column)
# ──────────────────────────────────────────────

class StepListPanel(QFrame):
    """Scrollable checklist of all inspection steps."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stepListPanel")
        self.setFixedWidth(220)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        title = QLabel("  INSPECTION STEPS")
        title.setStyleSheet(
            "color: #58a6ff; font-size: 12px; font-weight: bold; "
            "padding: 8px 0 4px 0; border-bottom: 1px solid #30363d;"
        )
        outer.addWidget(title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._vbox = QVBoxLayout(self._inner)
        self._vbox.setContentsMargins(6, 4, 6, 6)
        self._vbox.setSpacing(2)
        self._vbox.addStretch()

        self._scroll.setWidget(self._inner)
        outer.addWidget(self._scroll, stretch=1)

        self._frames: List[QFrame] = []
        self._labels: List[QLabel] = []
        self._icons:  List[QLabel] = []
        self._current = -1

    def load_sequence(self, sequence: List[Dict]):
        # Clear old items
        for f in self._frames:
            self._vbox.removeWidget(f)
            f.deleteLater()
        self._frames.clear()
        self._labels.clear()
        self._icons.clear()
        self._current = -1

        for step in sequence:
            num  = step['step_num']
            face = step['input_face']
            hole = step['input_hole']

            row = QFrame()
            row.setStyleSheet("background: transparent; border-radius: 3px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 3, 4, 3)
            rl.setSpacing(5)

            icon = QLabel("○")
            icon.setStyleSheet("color: #484f58; font-size: 12px; min-width: 14px;")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text = QLabel(f"{num:02d}.  Face {face} · {hole}")
            text.setStyleSheet("color: #8b949e; font-size: 11px;")

            rl.addWidget(icon)
            rl.addWidget(text, stretch=1)

            self._vbox.insertWidget(self._vbox.count() - 1, row)
            self._frames.append(row)
            self._labels.append(text)
            self._icons.append(icon)

    def set_active(self, index: int):
        # Reset previous (if not already pass/fail)
        if 0 <= self._current < len(self._frames):
            prev = self._frames[self._current]
            if not prev.property("done"):
                prev.setStyleSheet("background: transparent; border-radius: 3px;")
                self._labels[self._current].setStyleSheet("color: #8b949e; font-size: 11px;")
                self._icons[self._current].setText("○")
                self._icons[self._current].setStyleSheet("color: #484f58; font-size: 12px; min-width: 14px;")

        self._current = index
        if 0 <= index < len(self._frames):
            f = self._frames[index]
            f.setStyleSheet(
                "background-color: #1f3a5f; border-left: 3px solid #58a6ff; border-radius: 3px;"
            )
            self._labels[index].setStyleSheet("color: #e6edf3; font-size: 11px; font-weight: bold;")
            self._icons[index].setText("▶")
            self._icons[index].setStyleSheet("color: #58a6ff; font-size: 12px; min-width: 14px;")
            self._scroll.ensureWidgetVisible(f)

    def mark_result(self, index: int, passed: bool):
        if not (0 <= index < len(self._frames)):
            return
        f = self._frames[index]
        f.setProperty("done", True)
        if passed:
            f.setStyleSheet("background-color: #0f2d1a; border-left: 3px solid #3fb950; border-radius: 3px;")
            self._labels[index].setStyleSheet("color: #3fb950; font-size: 11px;")
            self._icons[index].setText("✓")
            self._icons[index].setStyleSheet("color: #3fb950; font-size: 12px; min-width: 14px;")
        else:
            f.setStyleSheet("background-color: #2d0f0f; border-left: 3px solid #f85149; border-radius: 3px;")
            self._labels[index].setStyleSheet("color: #f85149; font-size: 11px;")
            self._icons[index].setText("✗")
            self._icons[index].setStyleSheet("color: #f85149; font-size: 12px; min-width: 14px;")


# ──────────────────────────────────────────────
# InstructionPanel  (center column)
# ──────────────────────────────────────────────

class InstructionPanel(QFrame):
    """Large operator instruction: what to insert and what to expect."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("instructionPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)

        # Step counter
        self.step_lbl = QLabel("STEP — / —")
        self.step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_lbl.setStyleSheet("color: #8b949e; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.step_lbl)

        _div1 = QFrame(); _div1.setFrameShape(QFrame.Shape.HLine)
        _div1.setStyleSheet("color: #30363d;")
        layout.addWidget(_div1)

        # INSERT LASER INTO
        lbl_insert = QLabel("INSERT LASER INTO:")
        lbl_insert.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_insert.setStyleSheet("color: #8b949e; font-size: 13px;")
        layout.addWidget(lbl_insert)

        self.face_hole_lbl = QLabel("—")
        self.face_hole_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.face_hole_lbl.setWordWrap(True)
        self.face_hole_lbl.setStyleSheet("color: #f0f6fc; font-size: 30px; font-weight: bold;")
        layout.addWidget(self.face_hole_lbl)

        layout.addSpacing(10)

        # EXPECT LIGHT AT
        lbl_expect = QLabel("EXPECT LIGHT AT:")
        lbl_expect.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_expect.setStyleSheet("color: #8b949e; font-size: 13px;")
        layout.addWidget(lbl_expect)

        self._out_widget = QWidget()
        self._out_widget.setStyleSheet("background: transparent;")
        self._out_layout = QVBoxLayout(self._out_widget)
        self._out_layout.setContentsMargins(0, 0, 0, 0)
        self._out_layout.setSpacing(3)
        self._out_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._out_widget)

        layout.addStretch()

        _div2 = QFrame(); _div2.setFrameShape(QFrame.Shape.HLine)
        _div2.setStyleSheet("color: #30363d;")
        layout.addWidget(_div2)

        # Status
        self.status_lbl = QLabel("⏸  WAITING")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #8b949e; font-size: 22px; font-weight: bold;")
        layout.addWidget(self.status_lbl)

        # Countdown timer label (60s limit)
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_lbl.setStyleSheet("color: #8b949e; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.countdown_lbl)

        # Timeout Progress Bar (60s)
        self.timeout_bar = QProgressBar()
        self.timeout_bar.setRange(0, 600)  # 60.0 seconds (tenths)
        self.timeout_bar.setValue(600)
        self.timeout_bar.setTextVisible(False)
        self.timeout_bar.setFixedHeight(6)
        self.timeout_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #30363d;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #1f6feb;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.timeout_bar)

        layout.addSpacing(10)

        # Monitoring bar (Signal Verification)
        self.monitor_bar = QProgressBar()
        self.monitor_bar.setRange(0, 100)
        self.monitor_bar.setValue(0)
        self.monitor_bar.setFormat("Signal Verification: %p%")
        self.monitor_bar.setFixedHeight(16)
        self.monitor_bar.hide()
        layout.addWidget(self.monitor_bar)

        layout.addSpacing(6)

        # Pass / Fail counters
        row = QHBoxLayout()
        row.setSpacing(20)
        row.addStretch()

        pc = QVBoxLayout()
        self.pass_count = QLabel("0")
        self.pass_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pass_count.setStyleSheet("color: #3fb950; font-size: 22px; font-weight: bold;")
        pl = QLabel("PASS")
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.setStyleSheet("color: #3fb950; font-size: 11px; font-weight: bold;")
        pc.addWidget(self.pass_count); pc.addWidget(pl)

        fc = QVBoxLayout()
        self.fail_count = QLabel("0")
        self.fail_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fail_count.setStyleSheet("color: #f85149; font-size: 22px; font-weight: bold;")
        fl = QLabel("FAIL")
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.setStyleSheet("color: #f85149; font-size: 11px; font-weight: bold;")
        fc.addWidget(self.fail_count); fc.addWidget(fl)

        row.addLayout(pc); row.addLayout(fc)
        row.addStretch()
        layout.addLayout(row)

        self._pass_total = 0
        self._fail_total = 0
        self._out_labels: List[QLabel] = []

    # ── Public API ──────────────────────────────

    def show_step(self, step: Dict, total_steps: int):
        num  = step.get('step_num', '?')
        face = step.get('input_face', '?')
        hole = step.get('input_hole', '?')
        outs = step.get('expected_outputs', [])

        self.step_lbl.setText(f"STEP  {num}  of  {total_steps}")
        self.face_hole_lbl.setText(f"Face {face}  ·  {hole}")

        for lbl in self._out_labels:
            self._out_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._out_labels.clear()

        for out in outs:
            lbl = QLabel(f"● Face {out.get('face','?')}  →  {out.get('hole_id','?')}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #c9d1d9; font-size: 13px;")
            self._out_layout.addWidget(lbl)
            self._out_labels.append(lbl)

        self.set_waiting()

    def set_waiting(self):
        self.status_lbl.setText("⏸  WAITING FOR LASER")
        self.status_lbl.setStyleSheet("color: #8b949e; font-size: 22px; font-weight: bold;")
        self.monitor_bar.hide()
        self.monitor_bar.setValue(0)
        self.countdown_lbl.setText("Time Left: 60s")
        self.countdown_lbl.setStyleSheet("color: #8b949e; font-size: 14px; font-weight: bold;")
        self.timeout_bar.show()
        self.timeout_bar.setValue(600)
        self._update_timeout_bar_color(60)

    def set_monitoring(self, pct: int = 0):
        self.status_lbl.setText("⏱  MONITORING...")
        self.status_lbl.setStyleSheet("color: #58a6ff; font-size: 22px; font-weight: bold;")
        self.monitor_bar.show()
        self.monitor_bar.setValue(pct)

    def set_pass(self):
        self.status_lbl.setText("✓  PASS")
        self.status_lbl.setStyleSheet("color: #3fb950; font-size: 28px; font-weight: bold;")
        self.monitor_bar.hide()
        self.timeout_bar.hide()
        self.countdown_lbl.setText("")
        self._pass_total += 1
        self.pass_count.setText(str(self._pass_total))

    def set_fail(self):
        self.status_lbl.setText("✗  FAIL")
        self.status_lbl.setStyleSheet("color: #f85149; font-size: 28px; font-weight: bold;")
        self.monitor_bar.hide()
        self.timeout_bar.hide()
        self.countdown_lbl.setText("")
        self._fail_total += 1
        self.fail_count.setText(str(self._fail_total))

    def set_countdown(self, seconds_remaining: int):
        """Update the countdown label and progress bar."""
        self.countdown_lbl.setText(f"Time Left: {seconds_remaining}s")
        self.timeout_bar.setValue(seconds_remaining * 10)
        self._update_timeout_bar_color(seconds_remaining)

        if seconds_remaining <= 10:
            self.countdown_lbl.setStyleSheet("color: #f85149; font-size: 16px; font-weight: bold;")
        elif seconds_remaining <= 20:
            self.countdown_lbl.setStyleSheet("color: #d29922; font-size: 15px; font-weight: bold;")
        else:
            self.countdown_lbl.setStyleSheet("color: #8b949e; font-size: 14px; font-weight: bold;")

    def _update_timeout_bar_color(self, seconds: int):
        color = "#1f6feb" # Blue
        if seconds <= 10:
            color = "#da3633" # Red
        elif seconds <= 20:
            color = "#d29922" # Orange
            
        self.timeout_bar.setStyleSheet(f"""
            QProgressBar {{

                border: none;
                background-color: #30363d;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)


# ──────────────────────────────────────────────
# OverrideDialog
# ──────────────────────────────────────────────

class OverrideDialog(QDialog):
    """Manual override dialog."""

    def __init__(self, rule_ids: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manual Override")
        self.setFixedSize(360, 200)
        self.setStyleSheet(DARK_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Manual Inspection Override")
        title.setStyleSheet("color: #f0f6fc; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        rule_row = QHBoxLayout()
        rule_row.addWidget(QLabel("Rule:"))
        self.rule_combo = QComboBox()
        self.rule_combo.addItems(rule_ids)
        self.rule_combo.setMinimumWidth(200)
        rule_row.addWidget(self.rule_combo, stretch=1)
        layout.addLayout(rule_row)

        radio_row = QHBoxLayout()
        radio_row.addWidget(QLabel("Result:"))
        self.radio_pass = QRadioButton("PASS")
        self.radio_pass.setStyleSheet("color: #3fb950; font-weight: bold;")
        self.radio_fail = QRadioButton("FAIL")
        self.radio_fail.setStyleSheet("color: #f85149; font-weight: bold;")
        self.radio_pass.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.radio_pass)
        grp.addButton(self.radio_fail)
        radio_row.addWidget(self.radio_pass)
        radio_row.addWidget(self.radio_fail)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.setStyleSheet(
            "QPushButton { background-color: #21262d; color: #e6edf3; "
            "border: 1px solid #30363d; border-radius: 4px; padding: 5px 14px; }"
            "QPushButton:hover { background-color: #30363d; }"
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_selection(self):
        return self.rule_combo.currentText(), ("PASS" if self.radio_pass.isChecked() else "FAIL")


# ──────────────────────────────────────────────
# Selection Pages
# ──────────────────────────────────────────────

class ManifoldSelectionPage(QWidget):
    """Initial landing page to select the manifold model."""
    sig_manifold_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("manifoldSelectionPage")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header banner ──
        header = QFrame()
        header.setStyleSheet("background-color: #161b22;")
        header.setFixedHeight(120)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 30, 40, 30)
        header_layout.setSpacing(8)

        title_lbl = QLabel("⬡  MANIFOLD INSPECTION SYSTEM")
        title_lbl.setStyleSheet("color: #f0f6fc; font-size: 28px; font-weight: bold; letter-spacing: 2px; background-color: transparent;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(title_lbl)
        layout.addWidget(header)

        # ── Body ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(40)

        # Manifold Dropdown
        self.combo_manifold = QComboBox()
        self.combo_manifold.addItems(["DALIA", "Manifold 2", "Manifold 3"])
        self.combo_manifold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_manifold.setStyleSheet("""
            QComboBox {
                background-color: #21262d; color: #ffffff; font-weight: bold;
                font-size: 24px; padding: 20px 40px; border: 2px solid #30363d; border-radius: 8px;
                min-width: 300px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #21262d; color: #ffffff;
                font-size: 20px; selection-background-color: #388bfd;
            }
        """)
        body_layout.addWidget(self.combo_manifold)

        # Start Inspection Button
        self.btn_start = QPushButton("▶  START INSPECTION")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #238636; color: #ffffff; font-weight: bold;
                font-size: 20px; padding: 25px 50px; border: none; border-radius: 8px;
                min-width: 300px;
            }
            QPushButton:hover { background-color: #2ea043; }
        """)
        self.btn_start.clicked.connect(lambda: self.sig_manifold_selected.emit(self.combo_manifold.currentText()))
        body_layout.addWidget(self.btn_start)

        info_lbl = QLabel(
            "Active Cameras: Face A · Face B · Face C · Face D · Face E   |   "
            "Face F: Not Available (POC)"
        )
        info_lbl.setStyleSheet("color: #484f58; font-size: 13px; background-color: transparent;")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(info_lbl)

        layout.addWidget(body, stretch=1)


class ModeSelectionPage(QWidget):
    """Second landing page for mode selection."""
    sig_mode_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modeSelectionPage")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header banner ──
        header = QFrame()
        header.setStyleSheet("background-color: #161b22;")
        header.setFixedHeight(120)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(40, 30, 40, 30)
        header_layout.setSpacing(8)

        title_lbl = QLabel("⬡  MANIFOLD INSPECTION SYSTEM")
        title_lbl.setStyleSheet("color: #f0f6fc; font-size: 28px; font-weight: bold; letter-spacing: 2px; background-color: transparent;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header_layout.addWidget(title_lbl)
        layout.addWidget(header)

        # ── Body ──
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(40)

        # Mode buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(40)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Sequential button + description
        seq_col = QVBoxLayout()
        seq_col.setSpacing(16)
        seq_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_sequential = QPushButton("▶  Sequential Inspection")
        self.btn_sequential.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sequential.setStyleSheet("""
            QPushButton {
                background-color: #238636; color: #ffffff; font-weight: bold;
                font-size: 20px; padding: 25px 50px; border: none; border-radius: 8px;
                min-width: 300px; min-height: 100px;
            }
            QPushButton:hover { background-color: #2ea043; }
        """)
        self.btn_sequential.clicked.connect(lambda: self.sig_mode_selected.emit("sequential"))

        seq_desc = QLabel("Guided step-by-step inspection.\nSystem tells you exactly which hole\nto insert the laser into.")
        seq_desc.setStyleSheet("color: #8b949e; font-size: 14px; background-color: transparent; line-height: 1.5;")
        seq_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        seq_col.addWidget(self.btn_sequential)
        seq_col.addWidget(seq_desc)

        # Custom button
        cust_col = QVBoxLayout()
        cust_col.setSpacing(16)
        cust_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_custom = QPushButton("⚙  Custom Inspection")
        self.btn_custom.setEnabled(False)
        self.btn_custom.setStyleSheet("""
            QPushButton {
                background-color: #21262d; color: #484f58; font-weight: bold;
                font-size: 20px; padding: 25px 50px; border: 2px solid #30363d; border-radius: 8px;
                min-width: 300px; min-height: 100px;
            }
        """)

        cust_desc = QLabel("Define your own inspection order.\nSelect specific holes and rules\nto test manually.\n\n[ Coming Soon ]")
        cust_desc.setStyleSheet("color: #3d444d; font-size: 14px; background-color: transparent; line-height: 1.5;")
        cust_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cust_col.addWidget(self.btn_custom)
        cust_col.addWidget(cust_desc)

        btn_row.addLayout(seq_col)
        btn_row.addLayout(cust_col)
        body_layout.addLayout(btn_row)

        info_lbl = QLabel("Active Cameras: Face A · Face B · Face C · Face D · Face E   |   Face F: Not Available (POC)")
        info_lbl.setStyleSheet("color: #484f58; font-size: 13px; background-color: transparent;")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(info_lbl)

        layout.addWidget(body, stretch=1)

        layout.addWidget(body, stretch=1)


# ──────────────────────────────────────────────
# DashboardWindow
# ──────────────────────────────────────────────

class DashboardWindow(QMainWindow):
    """Main window: header + control bar + 3-column body + progress footer."""

    sig_start    = pyqtSignal()
    sig_stop     = pyqtSignal()
    sig_pause    = pyqtSignal()
    sig_resume   = pyqtSignal()
    sig_override = pyqtSignal(str, str)
    sig_mode_selected = pyqtSignal(str)
    sig_manifold_selected = pyqtSignal(str)

    def __init__(self, total_rules: int = 0,
                 cameras: Optional[List[Dict[str, Any]]] = None):
        super().__init__()
        self.setWindowTitle("Manifold Inspection System")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)
        self.setStyleSheet(DARK_STYLESHEET)

        # Face → USB index mapping
        self._face_to_index: Dict[str, int] = {}
        if cameras:
            for c in cameras:
                if c.get("face") and c.get("usb_index") is not None:
                    self._face_to_index[c["face"]] = c["usb_index"]
        else:
            try:
                import os, json
                p = os.path.join("config", "cameras.json")
                if os.path.exists(p):
                    data = json.load(open(p))
                    for c in data.get("cameras", []):
                        if c.get("face") and c.get("usb_index") is not None:
                            self._face_to_index[c["face"]] = c["usb_index"]
            except Exception:
                pass

        self._rule_ids: list = []
        self._guided_sequence: List[Dict] = []
        self._current_step_index: int = 0

        self.selected_manifold = None
        self.selected_mode = None

        # ── Central Widget & Global Layout ──
        central = QWidget()
        self.setCentralWidget(central)
        global_layout = QVBoxLayout(central)
        global_layout.setContentsMargins(0, 0, 0, 0)
        global_layout.setSpacing(0)

        # ── Global Header ──
        self.global_header = QFrame()
        self.global_header.setObjectName("headerBar")
        self.global_header.setFixedHeight(46)
        hl = QHBoxLayout(self.global_header)
        hl.setContentsMargins(16, 0, 16, 0)

        title_lbl = QLabel("⬡  MANIFOLD INSPECTION SYSTEM")
        title_lbl.setObjectName("headerTitle")
        hl.addWidget(title_lbl)
        hl.addStretch()

        self.header_status = QLabel("● STOPPED")
        self.header_status.setObjectName("headerStatus")
        self.header_status.setStyleSheet(
            "background-color: #484f58; color: #fff; font-weight: bold; "
            "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
        )
        self.header_status.hide()  # Hidden until dashboard feed
        hl.addWidget(self.header_status)

        self.clock_lbl = QLabel()
        self.clock_lbl.setObjectName("headerClock")
        self.clock_lbl.hide()      # Hidden until dashboard feed
        hl.addWidget(self.clock_lbl)
        global_layout.addWidget(self.global_header)
        self.global_header.hide()  # Hidden on startup pages

        # ── Central Stack ──
        self.stacked_widget = QStackedWidget()
        global_layout.addWidget(self.stacked_widget, stretch=1)
        
        # Stack 0: Mode Selection (First page)
        self.mode_page = ModeSelectionPage()
        self.mode_page.sig_mode_selected.connect(self._on_mode_selected)
        self.stacked_widget.addWidget(self.mode_page)

        # Stack 1: Manifold Selection (Second page)
        self.manifold_page = ManifoldSelectionPage()
        self.manifold_page.sig_manifold_selected.connect(self._on_manifold_selected)
        self.stacked_widget.addWidget(self.manifold_page)

        # Stack 2: Live Dashboard
        self.dashboard_page = QWidget()
        self.stacked_widget.addWidget(self.dashboard_page)

        root = QVBoxLayout(self.dashboard_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Control bar ──
        ctrl_bar = QFrame()
        ctrl_bar.setObjectName("controlBar")
        ctrl_bar.setFixedHeight(42)
        cl = QHBoxLayout(ctrl_bar)
        cl.setContentsMargins(14, 4, 14, 4)
        cl.setSpacing(8)

        self.btn_start  = self._make_btn("▶  START",   "btnStart",  self._on_start)
        self.btn_stop   = self._make_btn("■  STOP",    "btnStop",   self._on_stop,   enabled=False)
        self.btn_pause  = self._make_btn("⏸  PAUSE",   "btnPause",  self._on_pause,  enabled=False)
        self.btn_resume = self._make_btn("⏵  RESUME",  "btnResume", self._on_resume, enabled=False)
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_resume):
            cl.addWidget(b)

        cl.addSpacing(12)
        self.btn_override = self._make_btn("✎  OVERRIDE", "btnOverride", self._on_override, enabled=False)
        cl.addWidget(self.btn_override)
        cl.addStretch()

        self.state_lbl = QLabel("STOPPED")
        self.state_lbl.setStyleSheet("color: #8b949e; font-size: 12px; font-weight: bold;")
        cl.addWidget(self.state_lbl)
        root.addWidget(ctrl_bar)

        # ── Body: 3 columns ──
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(10, 10, 10, 10)
        body_layout.setSpacing(10)

        # LEFT — step list
        self.step_list = StepListPanel()
        body_layout.addWidget(self.step_list)

        # CENTER — instruction panel (narrower)
        self.instruction_panel = InstructionPanel()
        self.instruction_panel.setFixedWidth(320)
        body_layout.addWidget(self.instruction_panel)

        # RIGHT — Dynamic Camera Area (Hero + Thumbnails)
        right_panel = QWidget()
        right_panel.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        # 1. Hero Section (Top, larger)
        self.hero_frame = QFrame()
        self.hero_frame.setStyleSheet("background-color: #0d1117; border: 1px solid #30363d; border-radius: 6px;")
        self.hero_layout = QVBoxLayout(self.hero_frame)
        self.hero_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.hero_frame, stretch=6) # 60% height

        # 2. Thumbnails Section (Bottom, grid)
        self.thumb_frame = QFrame()
        self.thumb_frame.setStyleSheet("background: transparent;")
        self.thumb_layout = QGridLayout(self.thumb_frame)
        self.thumb_layout.setContentsMargins(0, 0, 0, 0)
        self.thumb_layout.setSpacing(6)
        right_layout.addWidget(self.thumb_frame, stretch=4) # 40% height

        body_layout.addWidget(right_panel, stretch=1)
        root.addWidget(body, stretch=1)

        # Create All 6 Camera Widgets
        self.camera_widgets: Dict[str, CameraWidget] = {}
        faces = ['A', 'B', 'C', 'D', 'E', 'F']
        for face in faces:
            cw = CameraWidget(face, usb_index=self._face_to_index.get(face))
            self.camera_widgets[f"CAM_{face}"] = cw
        
        # Initialize Layout (Hero = A, others = thumbnails)
        self._current_hero = None
        self.set_hero_camera('A')

        # ── Footer: progress bar ──
        footer = QFrame()
        footer.setStyleSheet("background-color: #161b22; border-top: 1px solid #30363d;")
        footer.setFixedHeight(34)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 4, 14, 4)
        fl.setSpacing(10)

        prog_lbl = QLabel("Progress:")
        prog_lbl.setStyleSheet("color: #8b949e; font-size: 12px;")
        fl.addWidget(prog_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(total_rules, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m steps")
        self.progress_bar.setFixedHeight(18)
        fl.addWidget(self.progress_bar, stretch=1)
        root.addWidget(footer)

        # ── Global Footer ──
        footer = QFrame()
        footer.setStyleSheet("background-color: #161b22; border-top: 1px solid #21262d;")
        footer.setFixedHeight(40)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 0, 20, 0)
        ver_lbl = QLabel("POC v1.0  —  GnB Plant 8")
        ver_lbl.setStyleSheet("color: #3d444d; font-size: 12px; background-color: transparent;")
        footer_layout.addWidget(ver_lbl)
        footer_layout.addStretch()
        global_layout.addWidget(footer)

        # ── Clock timer ──
        self._clock = QTimer()
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

        self.stacked_widget.setCurrentIndex(0)
        self.showMaximized()

    def _on_mode_selected(self, mode: str):
        self.selected_mode = mode
        self.stacked_widget.setCurrentIndex(1)

    def _on_manifold_selected(self, manifold: str):
        self.selected_manifold = manifold
        self.stacked_widget.setCurrentIndex(2)
        self.global_header.show()
        self.header_status.show()
        self.clock_lbl.show()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents() # Force Qt to paint the dashboard before main.py sleeps
        self.sig_manifold_selected.emit(manifold) # Signal main.py that UI setup is complete

    # ── Helpers ─────────────────────────────────

    def _make_btn(self, text, obj_name, slot, enabled=True):
        b = QPushButton(text)
        b.setObjectName(obj_name)
        b.setEnabled(enabled)
        b.clicked.connect(slot)
        return b

    def _tick_clock(self):
        self.clock_lbl.setText(datetime.now().strftime("  %H:%M:%S"))

    # ── Guided sequence API ──────────────────────

    def load_guided_sequence(self, sequence: List[Dict]):
        self._guided_sequence = sequence
        total = len(sequence)
        self.step_list.load_sequence(sequence)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"%v / {total} steps")
        if sequence:
            self._current_step_index = 0
            self.step_list.set_active(0)
            self.instruction_panel.show_step(sequence[0], total)

    def set_hero_camera(self, face_id: str):
        """
        Promotes the given face_id camera to the Hero slot.
        Demotes the previous hero to the thumbnail grid.
        """
        target_cam = self.camera_widgets.get(f"CAM_{face_id}")
        if not target_cam:
            return

        if self._current_hero == face_id:
            return  # Already hero

        # 1. Remove previous hero (if any) and move to thumbnails
        if self._current_hero:
            prev_cam = self.camera_widgets.get(f"CAM_{self._current_hero}")
            if prev_cam:
                self.hero_layout.removeWidget(prev_cam)
                prev_cam.setParent(None) # Detach
        
        # 2. Clear Hero Layout (just in case)
        while self.hero_layout.count():
            item = self.hero_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # 3. Re-build Thumbnail Grid
        # We want to show ALL cameras EXCEPT the new hero in a nice grid.
        # Clean current thumbnails
        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        # Add cameras to thumbnail grid, skipping the target hero
        faces = ['A', 'B', 'C', 'D', 'E', 'F']
        thumb_idx = 0
        for f in faces:
            if f == face_id:
                continue
            
            cw = self.camera_widgets.get(f"CAM_{f}")
            if cw:
                row, col = divmod(thumb_idx, 3) # 3 columns for thumbnails
                self.thumb_layout.addWidget(cw, row, col)
                cw.setVisible(True)
                thumb_idx += 1

        # 4. Add Target to Hero
        self.hero_layout.addWidget(target_cam)
        target_cam.setVisible(True)
        self._current_hero = face_id

    def update_guided_step(self, step_index: int):
        if not self._guided_sequence:
            return
        total = len(self._guided_sequence)
        if 0 <= step_index < total:
            self._current_step_index = step_index
            self.step_list.set_active(step_index)
            step = self._guided_sequence[step_index]
            self.instruction_panel.show_step(step, total)
            self.progress_bar.setValue(step_index)
            
            # Dynamic Hero Update
            input_face = step.get('input_face')
            if input_face:
                self.set_hero_camera(input_face)

    def update_step_result(self, step_index: int, passed: bool):
        self.step_list.mark_result(step_index, passed)
        if passed:
            self.instruction_panel.set_pass()
        else:
            self.instruction_panel.set_fail()
        self.progress_bar.setValue(step_index + 1)

    def update_monitoring_progress(self, pct: int):
        self.instruction_panel.set_monitoring(pct)

    # ── Camera / health updates ──────────────────

    def update_frame(self, camera_id: str, frame: np.ndarray):
        w = self.camera_widgets.get(camera_id)
        if w:
            w.update_frame(frame)

    def update_health(self, camera_id: str, fps: float, det_count: int):
        w = self.camera_widgets.get(camera_id)
        if w:
            w.update_stats(fps, det_count)

    # ── Legacy methods (called by main.py) ──────

    def update_result(self, result: Dict[str, Any]):
        """Called by main.py for every PASS/FAIL — update header status."""
        res = result.get('result', '')
        if res == 'FAIL':
            self.header_status.setText("● FAIL DETECTED")
            self.header_status.setStyleSheet(
                "background-color: #da3633; color: #fff; font-weight: bold; "
                "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
            )
        elif res == 'PASS':
            self.header_status.setText("● RUNNING")
            self.header_status.setStyleSheet(
                "background-color: #238636; color: #fff; font-weight: bold; "
                "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
            )

    def update_detected_state(self, detected: List[str]):
        """No-op in guided mode — kept for compatibility."""
        pass

    def update_monitoring(self, monitoring: List[Dict[str, Any]]):
        """No-op in guided mode — kept for compatibility."""
        pass

    def set_rule_ids(self, rule_ids: list):
        self._rule_ids = rule_ids

    # ── Control button handlers ──────────────────

    def _on_start(self):
        self.sig_start.emit()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(True)
        self.state_lbl.setText("RUNNING")
        self.header_status.setText("● RUNNING")
        self.header_status.setStyleSheet(
            "background-color: #238636; color: #fff; font-weight: bold; "
            "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
        )

    def _on_stop(self):
        self.sig_stop.emit()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(False)
        self.state_lbl.setText("STOPPED")
        self.header_status.setText("● STOPPED")
        self.header_status.setStyleSheet(
            "background-color: #484f58; color: #fff; font-weight: bold; "
            "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
        )

    def _on_pause(self):
        self.sig_pause.emit()
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)
        self.state_lbl.setText("PAUSED")
        self.header_status.setText("● PAUSED")
        self.header_status.setStyleSheet(
            "background-color: #9e6a03; color: #fff; font-weight: bold; "
            "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
        )

    def _on_resume(self):
        self.sig_resume.emit()
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.state_lbl.setText("RUNNING")
        self.header_status.setText("● RUNNING")
        self.header_status.setStyleSheet(
            "background-color: #238636; color: #fff; font-weight: bold; "
            "padding: 3px 10px; border-radius: 4px; font-size: 12px;"
        )

    def _on_override(self):
        if not self._rule_ids:
            return
        dlg = OverrideDialog(self._rule_ids, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rule_id, result = dlg.get_selection()
            self.sig_override.emit(rule_id, result)


# ──────────────────────────────────────────────
# OpenCV fallback (headless / no PyQt6)
# ──────────────────────────────────────────────

class OpenCVDashboard:
    """Minimal OpenCV-based display when PyQt6 is unavailable."""

    def __init__(self, total_rules: int = 0, cameras=None):
        self._frames: Dict[str, Any] = {}
        self._pass = 0
        self._fail = 0

    def update_frame(self, camera_id: str, frame):
        self._frames[camera_id] = frame

    def update_health(self, camera_id: str, fps: float, det_count: int):
        pass

    def update_result(self, result: Dict[str, Any]):
        res = result.get('result', '')
        if res == 'PASS':
            self._pass += 1
        elif res == 'FAIL':
            self._fail += 1
        print(f"[Dashboard] {res}  PASS:{self._pass}  FAIL:{self._fail}")

    def update_detected_state(self, detected):
        pass

    def update_monitoring(self, monitoring):
        pass

    def load_guided_sequence(self, sequence):
        pass

    def update_guided_step(self, index):
        pass

    def update_step_result(self, index, passed):
        pass

    def update_monitoring_progress(self, pct):
        pass

    def set_rule_ids(self, rule_ids):
        pass

    def show(self):
        import cv2
        for cid, frame in self._frames.items():
            cv2.imshow(cid, frame)
        return cv2.waitKey(1) & 0xFF

    def close(self):
        import cv2
        cv2.destroyAllWindows()


# ──────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────

def create_dashboard(total_rules: int = 0,
                     force_cv: bool = False,
                     cameras=None):
    """
    Returns (dashboard, qt_app_or_None).
    If PyQt6 is available and force_cv is False, returns a DashboardWindow.
    Otherwise returns an OpenCVDashboard.
    """
    if HAS_PYQT6 and not force_cv:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setStyleSheet(DARK_STYLESHEET)
        win = DashboardWindow(total_rules=total_rules, cameras=cameras)
        win.show()
        return win, app
    else:
        return OpenCVDashboard(total_rules=total_rules, cameras=cameras), None

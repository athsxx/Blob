"""
Operator Dashboard — PyQt6  (Guided Inspection Mode)

Stacked pages (QStackedWidget indices):
  0 — Mode: Sequential vs Manual inspection
  1 — Manifold: DALIA / Manifold 2 / Manifold 3
  2 — Manual setup only: dropdowns for manifold, input face, rule (then Continue)
  3 — Pre-inspection: optional ROI calibration, then Continue to live view
  4 — Live dashboard (cameras, steps, START/STOP, etc.)

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

import json
import os
import subprocess
import sys
import time
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from logic_engine import rule_has_unavailable_output
from config_loader import manifold_labels, manifold_folder_for_label

# Faces with cameras (matches main.py sequential guided filter)
MANUAL_AVAILABLE_FACES: Set[str] = {"A", "B", "C", "D", "E", "F"}

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout,
        QHBoxLayout, QGridLayout, QFrame, QProgressBar, QScrollArea,
        QSizePolicy, QPushButton, QDialog, QComboBox, QRadioButton,
        QButtonGroup, QDialogButtonBox, QStackedWidget, QSpinBox,
        QCheckBox, QMessageBox, QFormLayout,
    )
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import QImage, QPixmap, QFont, QColor, QPalette, QCloseEvent
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False
    print("[Dashboard] PyQt6 not installed. Install with: pip install PyQt6")

if HAS_PYQT6:
    try:
        from camera_setup_ui import CameraSetupDialog, CalibrateRoiDialog
        from manifold_setup_ui import AddManifoldDialog
    except ImportError:
        CameraSetupDialog = None  # type: ignore
        CalibrateRoiDialog = None  # type: ignore
        AddManifoldDialog = None  # type: ignore
else:
    CameraSetupDialog = None  # type: ignore
    CalibrateRoiDialog = None  # type: ignore
    AddManifoldDialog = None  # type: ignore


# ──────────────────────────────────────────────
# STYLESHEET
# ──────────────────────────────────────────────

DARK_STYLESHEET = """
/* ── Base ── */
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #e6edf3;
    font-family: 'SF Pro Text', 'SF Pro Display', 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}
QLabel { color: #e6edf3; }

/* ── Wizard / setup pages (shared) ── */
QFrame#brandStrip {
    background-color: #161b22;
    border: none;
    border-bottom: 1px solid #30363d;
}
QLabel#pageKicker {
    color: #8b949e;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.1em;
}
QLabel#pageTitleMain {
    color: #f0f6fc;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
}
QLabel#pageSubtitle {
    color: #8b949e;
    font-size: 13px;
    font-weight: normal;
}
QLabel#pageHint {
    color: #9da7b2;
    font-size: 13px;
    line-height: 1.5;
}
QLabel#pageMeta {
    color: #8b949e;
    font-size: 12px;
}
QLabel#formLabel {
    color: #8b949e;
    font-size: 12px;
    font-weight: 500;
    min-width: 120px;
}
QFrame#formCard {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
}
QFrame#modeCard {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 12px;
}
QPushButton#modeActionSeq {
    background-color: #238636;
    color: #ffffff;
    font-weight: 600;
    font-size: 15px;
    padding: 14px 20px;
    border: none;
    border-radius: 8px;
    min-height: 48px;
}
QPushButton#modeActionSeq:hover { background-color: #2ea043; }
QPushButton#modeActionSeq:pressed { background-color: #1f6e30; }
QPushButton#modeActionManual {
    background-color: #21262d;
    color: #e6edf3;
    font-weight: 600;
    font-size: 15px;
    padding: 14px 20px;
    border: 1px solid #388bfd;
    border-radius: 8px;
    min-height: 48px;
}
QPushButton#modeActionManual:hover {
    background-color: #1c2d4a;
    border-color: #58a6ff;
}
QPushButton#modeActionManual:pressed { background-color: #161b22; }

QComboBox#pageCombo {
    background-color: #21262d;
    color: #f0f6fc;
    font-weight: 500;
    font-size: 15px;
    padding: 12px 16px;
    border: 1px solid #30363d;
    border-radius: 8px;
    min-height: 24px;
    min-width: 280px;
}
QComboBox#pageCombo:hover { border-color: #484f58; }
QComboBox#pageCombo:focus { border-color: #388bfd; }
QComboBox#pageCombo::drop-down { border: none; width: 28px; }
QComboBox#pageCombo QAbstractItemView {
    background-color: #21262d;
    color: #f0f6fc;
    font-size: 14px;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
    border: 1px solid #30363d;
    padding: 4px;
}
QPushButton#pagePrimary {
    background-color: #238636;
    color: #ffffff;
    font-weight: 600;
    font-size: 15px;
    padding: 14px 28px;
    border: none;
    border-radius: 8px;
    min-width: 200px;
    min-height: 48px;
}
QPushButton#pagePrimary:hover { background-color: #2ea043; }
QPushButton#pagePrimary:pressed { background-color: #1f6e30; }
QPushButton#pageGhost {
    background-color: transparent;
    color: #8b949e;
    font-weight: 500;
    font-size: 13px;
    padding: 8px 16px;
    border: none;
    border-radius: 8px;
}
QPushButton#pageGhost:hover {
    color: #e6edf3;
    background-color: #21262d;
}
QPushButton#pageGhost:focus {
    border: none;
    outline: none;
}
QPushButton#pageLink {
    background-color: #21262d;
    color: #58a6ff;
    font-weight: 600;
    font-size: 13px;
    padding: 10px 18px;
    border: 1px solid #30363d;
    border-radius: 8px;
}
QPushButton#pageLink:hover {
    background-color: #30363d;
    border-color: #484f58;
}

/* Same height as primary — paired actions (e.g. Calibrate + Continue) */
QPushButton#pageSecondary {
    background-color: #21262d;
    color: #e6edf3;
    font-weight: 600;
    font-size: 15px;
    padding: 14px 28px;
    border: 1px solid #484f58;
    border-radius: 8px;
    min-width: 240px;
    min-height: 48px;
}
QPushButton#pageSecondary:hover {
    background-color: #30363d;
    border-color: #58a6ff;
    color: #f0f6fc;
}
QPushButton#pageSecondary:pressed {
    background-color: #161b22;
}

/* ── Live dashboard header ── */
QFrame#headerBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
}
QLabel#headerTitle {
    color: #f0f6fc;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: -0.01em;
}
QLabel#headerClock { color: #8b949e; font-size: 12px; }
QLabel#headerStatus {
    font-size: 11px;
    font-weight: 600;
    padding: 4px 12px;
    border-radius: 999px;
}

/* ── Control bar ── */
QFrame#controlBar {
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
}
QPushButton#btnStart {
    background-color: #238636;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 16px;
    border: none;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnStart:hover  { background-color: #2ea043; }
QPushButton#btnStart:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnStop {
    background-color: #da3633;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 16px;
    border: none;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnStop:hover  { background-color: #f85149; }
QPushButton#btnStop:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnPause {
    background-color: #9e6a03;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 16px;
    border: none;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnPause:hover  { background-color: #bb8009; }
QPushButton#btnPause:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnResume {
    background-color: #1f6feb;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 16px;
    border: none;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnResume:hover  { background-color: #388bfd; }
QPushButton#btnResume:disabled { background-color: #21262d; color: #484f58; }
QPushButton#btnOverride {
    background-color: #6e40c9;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 16px;
    border: none;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnOverride:hover  { background-color: #8957e5; }
QPushButton#btnOverride:disabled { background-color: #21262d; color: #484f58; }

/* ── Camera tiles ── */
QFrame#cameraCell {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
}
QFrame#cameraVideoShell {
    background-color: #010409;
    border: 1px solid #21262d;
    border-radius: 8px;
}
QFrame#heroCameraShell {
    background-color: #010409;
    border: 1px solid #30363d;
    border-radius: 10px;
}

QPushButton#btnSetup {
    background-color: #21262d;
    color: #e6edf3;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 14px;
    border: 1px solid #30363d;
    border-radius: 6px;
    min-height: 28px;
}
QPushButton#btnSetup:hover { background-color: #30363d; border-color: #484f58; }
QPushButton#btnSetup:disabled { background-color: #161b22; color: #484f58; border-color: #21262d; }

/* ── Step list & instruction ── */
QFrame#stepListPanel {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
}
QFrame#instructionPanel {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
}

/* ── Progress ── */
QProgressBar {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    text-align: center;
    color: #e6edf3;
    font-weight: 600;
    font-size: 11px;
    height: 22px;
}
QProgressBar::chunk {
    background-color: #238636;
    border-radius: 5px;
    margin: 1px;
}

/* ── Dialogs ── */
QDialog { background-color: #0d1117; color: #e6edf3; }
QComboBox {
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 20px;
}
QComboBox:hover { border-color: #484f58; }
QComboBox:focus { border-color: #388bfd; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #21262d;
    color: #e6edf3;
    selection-background-color: #1f6feb;
    selection-color: #ffffff;
    border: 1px solid #30363d;
}
QRadioButton { color: #e6edf3; font-size: 13px; spacing: 8px; }

/* ── Scrollbars ── */
QScrollBar:vertical {
    background: #0d1117;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #484f58; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

/* Step list title strip */
QLabel#stepPanelTitle {
    color: #58a6ff;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.07em;
    padding: 12px 14px 8px 14px;
    border-bottom: 1px solid #30363d;
    background-color: transparent;
}
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
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.feed_label = QLabel()
        self.feed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.feed_label.setMinimumSize(120, 90)
        label_text = f"USB {usb_index} · Face {face}" if usb_index is not None else f"Face {face}"
        self.feed_label.setText(f"{label_text}\nNO SIGNAL")
        self.feed_label.setStyleSheet(
            "background-color: transparent; border-radius: 6px; "
            "color: #484f58; font-size: 11px; font-weight: 600;"
        )
        self.feed_label.setToolTip(
            "Scaled preview only. Laser ROIs are saved in full camera resolution and are not affected by this display size."
        )

        video_shell = QFrame()
        video_shell.setObjectName("cameraVideoShell")
        shell_layout = QVBoxLayout(video_shell)
        shell_layout.setContentsMargins(4, 4, 4, 4)
        shell_layout.setSpacing(0)
        shell_layout.addWidget(self.feed_label, stretch=1)
        layout.addWidget(video_shell, stretch=1)

        # Overlays
        self._face_lbl = QLabel(label_text, self)
        self._face_lbl.setStyleSheet(
            "background-color: rgba(22,27,34,220); color: #79c0ff; "
            "font-weight: 600; font-size: 10px; padding: 4px 8px; border-radius: 4px;"
        )
        self._face_lbl.adjustSize()
        self._face_lbl.move(6, 6)

        self._fps_lbl = QLabel("-- fps", self)
        self._fps_lbl.setStyleSheet(
            "background-color: rgba(22,27,34,200); color: #8b949e; "
            "font-size: 10px; padding: 3px 7px; border-radius: 4px;"
        )
        self._fps_lbl.adjustSize()
        self._fps_lbl.move(6, 6 + self._face_lbl.height() + 4)

        # Target hole overlay (shown when this camera is inspecting a specific hole)
        self._target_lbl = QLabel("", self)
        self._target_lbl.setStyleSheet(
            "background-color: rgba(255,215,0,200); color: #0d1117; "
            "font-weight: 700; font-size: 11px; padding: 4px 10px; border-radius: 4px;"
        )
        self._target_lbl.hide()

    def set_target_label(self, hole_id: Optional[str] = None):
        """Show or hide the target hole indicator on this camera feed."""
        if hole_id:
            self._target_lbl.setText(f"→ {hole_id}")
            self._target_lbl.adjustSize()
            self._target_lbl.show()
            self._reposition_target_lbl()
        else:
            self._target_lbl.hide()

    def _reposition_target_lbl(self):
        """Position target label at top-right of the widget."""
        w = self.width()
        tw = self._target_lbl.width()
        self._target_lbl.move(w - tw - 8, 6)

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
        self.feed_label.setStyleSheet("background-color: transparent; border-radius: 6px;")

    def update_stats(self, fps: float, det_count: int):
        self._fps_lbl.setText(f"{fps:.1f} fps")
        self._fps_lbl.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._face_lbl.move(6, 6)
        self._fps_lbl.move(6, 6 + self._face_lbl.height() + 4)
        if self._target_lbl.isVisible():
            self._reposition_target_lbl()


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

        title = QLabel("INSPECTION STEPS")
        title.setObjectName("stepPanelTitle")
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
            row.setStyleSheet("background: transparent; border-radius: 6px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 3, 4, 3)
            rl.setSpacing(5)

            icon = QLabel("○")
            icon.setStyleSheet("color: #484f58; font-size: 12px; min-width: 14px;")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text = QLabel(f"{num:02d}.  {face} · {hole}")
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
                prev.setStyleSheet("background: transparent; border-radius: 6px;")
                self._labels[self._current].setStyleSheet("color: #8b949e; font-size: 11px;")
                self._icons[self._current].setText("○")
                self._icons[self._current].setStyleSheet("color: #484f58; font-size: 12px; min-width: 14px;")

        self._current = index
        if 0 <= index < len(self._frames):
            f = self._frames[index]
            f.setStyleSheet(
                "background-color: #1c2d4a; border-left: 3px solid #58a6ff; border-radius: 6px;"
            )
            self._labels[index].setStyleSheet("color: #e6edf3; font-size: 11px; font-weight: 600;")
            self._icons[index].setText("▶")
            self._icons[index].setStyleSheet("color: #58a6ff; font-size: 12px; min-width: 14px;")
            self._scroll.ensureWidgetVisible(f)

    def mark_result(self, index: int, passed: bool):
        if not (0 <= index < len(self._frames)):
            return
        f = self._frames[index]
        f.setProperty("done", True)
        if passed:
            f.setStyleSheet("background-color: #0f2d1a; border-left: 3px solid #3fb950; border-radius: 6px;")
            self._labels[index].setStyleSheet("color: #3fb950; font-size: 11px;")
            self._icons[index].setText("✓")
            self._icons[index].setStyleSheet("color: #3fb950; font-size: 12px; min-width: 14px;")
        else:
            f.setStyleSheet("background-color: #2d0f0f; border-left: 3px solid #f85149; border-radius: 6px;")
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
        self.face_hole_lbl.setText(f"{face}  ·  {hole}")

        for lbl in self._out_labels:
            self._out_layout.removeWidget(lbl)
            lbl.deleteLater()
        self._out_labels.clear()

        for out in outs:
            lbl = QLabel(f"● {out.get('face','?')}  →  {out.get('hole_id','?')}")
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

class ManualInspectionSetupPage(QWidget):
    """
    Custom / manual mode: pick manifold (again or change), input face, and rule from dropdowns.
    """
    sig_continue = pyqtSignal()
    sig_back = pyqtSignal()

    def __init__(self, project_root: str, config_dir: str, parent=None):
        super().__init__(parent)
        self._project_root = project_root
        self._config_dir = os.path.abspath(config_dir)
        self._rules_raw: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("brandStrip")
        header.setFixedHeight(112)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(48, 22, 48, 20)
        hl.setSpacing(6)
        kicker = QLabel("SESSION")
        kicker.setObjectName("pageKicker")
        kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Manual inspection")
        title.setObjectName("pageTitleMain")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Choose manifold, input face, and the rule to run as one guided check.")
        sub.setObjectName("pageSubtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        hl.addWidget(kicker)
        hl.addWidget(title)
        hl.addWidget(sub)
        layout.addWidget(header)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.setSpacing(24)
        bl.setContentsMargins(48, 24, 48, 32)
        bl.addStretch(1)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMaximumWidth(560)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 28, 28, 28)
        cl.setSpacing(18)

        form = QFormLayout()
        form.setSpacing(16)
        form.setHorizontalSpacing(20)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.combo_manifold = QComboBox()
        self.combo_manifold.setObjectName("pageCombo")
        self.combo_manifold.setMinimumWidth(360)
        self.combo_manifold.currentTextChanged.connect(self._on_manifold_changed)

        self.combo_face = QComboBox()
        self.combo_face.setObjectName("pageCombo")
        self.combo_face.setMinimumWidth(360)
        for f in "ABCDEF":
            self.combo_face.addItem(f"Face {f}", userData=f)
        self.combo_face.currentIndexChanged.connect(self._refill_rules_combo)

        self.combo_rule = QComboBox()
        self.combo_rule.setObjectName("pageCombo")
        self.combo_rule.setMinimumWidth(360)

        lb_m = QLabel("Manifold")
        lb_m.setObjectName("formLabel")
        lb_f = QLabel("Input face")
        lb_f.setObjectName("formLabel")
        lb_r = QLabel("Rule")
        lb_r.setObjectName("formLabel")
        form.addRow(lb_m, self.combo_manifold)
        form.addRow(lb_f, self.combo_face)
        form.addRow(lb_r, self.combo_rule)
        cl.addLayout(form)

        hint = QLabel(
            "Rules are filtered by the selected face. Entries that need a camera you do not have enabled are hidden."
        )
        hint.setWordWrap(True)
        hint.setObjectName("pageHint")
        cl.addWidget(hint)
        bl.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_back = QPushButton("Back")
        btn_back.setObjectName("pageGhost")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self.sig_back.emit)
        btn_go = QPushButton("Continue")
        btn_go.setObjectName("pagePrimary")
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.clicked.connect(self._emit_continue_if_ok)
        btn_row.addStretch()
        btn_row.addWidget(btn_back)
        btn_row.addWidget(btn_go)
        bl.addLayout(btn_row)

        bl.addStretch(2)
        layout.addWidget(body, stretch=1)

    def set_initial_manifold(self, name: str):
        idx = self.combo_manifold.findText(name)
        if idx >= 0:
            self.combo_manifold.setCurrentIndex(idx)

    def set_manifold_items(self, labels: List[str], select: Optional[str] = None) -> None:
        cur = self.combo_manifold.currentText()
        self.combo_manifold.clear()
        for L in labels:
            self.combo_manifold.addItem(L)
        if select and self.combo_manifold.findText(select) >= 0:
            self.combo_manifold.setCurrentText(select)
        elif cur and self.combo_manifold.findText(cur) >= 0:
            self.combo_manifold.setCurrentText(cur)
        elif self.combo_manifold.count() > 0:
            self.combo_manifold.setCurrentIndex(0)
        self._load_rules_file()
        self._refill_rules_combo()

    def _rules_path(self) -> str:
        label = self.combo_manifold.currentText()
        folder = manifold_folder_for_label(label, self._config_dir) or "DALIA"
        return os.path.normpath(
            os.path.join(self._config_dir, folder, "connectivity_rules.json")
        )

    def _load_rules_file(self) -> bool:
        path = self._rules_path()
        self._rules_raw = []
        if not os.path.isfile(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._rules_raw = data.get("rules", [])
        except (json.JSONDecodeError, OSError):
            self._rules_raw = []
        return bool(self._rules_raw)

    def _on_manifold_changed(self, _txt: str):
        self._load_rules_file()
        self._refill_rules_combo()

    def _refill_rules_combo(self):
        self.combo_rule.clear()
        face = self.combo_face.currentData()
        if not face:
            return
        for rule in self._rules_raw:
            inp = rule.get("input") or {}
            if inp.get("face") != face:
                continue
            if rule_has_unavailable_output(rule, MANUAL_AVAILABLE_FACES):
                continue
            rid = rule.get("rule_id", "")
            hid = inp.get("hole_id", "")
            self.combo_rule.addItem(f"{rid}  —  hole {hid}", userData=rid)
        if self.combo_rule.count() == 0:
            self.combo_rule.addItem("(no rules for this face)", userData=None)

    def reload_from_disk(self):
        self._load_rules_file()
        self._refill_rules_combo()

    def _emit_continue_if_ok(self):
        rid = self.combo_rule.currentData()
        if not rid:
            QMessageBox.warning(self, "Manual setup", "Select a rule.")
            return
        self.sig_continue.emit()

    def get_manifold(self) -> str:
        return self.combo_manifold.currentText()

    def get_rule_id(self) -> Optional[str]:
        return self.combo_rule.currentData()


class PreInspectionSetupPage(QWidget):
    """Optional ROI calibration before the live dashboard; main.py waits until Continue here."""

    sig_continue = pyqtSignal()
    sig_back = pyqtSignal()
    sig_calibrate = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("brandStrip")
        header.setFixedHeight(112)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(48, 22, 48, 20)
        hl.setSpacing(6)
        kick = QLabel("READY")
        kick.setObjectName("pageKicker")
        kick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Before live inspection")
        title.setObjectName("pageTitleMain")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Optional ROI calibration, then continue. Cameras start after you press Continue.")
        sub.setObjectName("pageSubtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        hl.addWidget(kick)
        hl.addWidget(title)
        hl.addWidget(sub)
        layout.addWidget(header)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.setSpacing(20)
        bl.setContentsMargins(48, 24, 48, 32)
        bl.addStretch(1)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMinimumWidth(500)
        card.setMaximumWidth(580)
        cvl = QVBoxLayout(card)
        cvl.setContentsMargins(24, 24, 24, 24)
        cvl.setSpacing(14)
        explain = QLabel()
        explain.setObjectName("pageHint")
        explain.setWordWrap(True)
        explain.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        explain.setMinimumWidth(440)
        explain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        explain.setTextFormat(Qt.TextFormat.RichText)
        explain.setText(
            "Face A through F maps to USB indices 0 through 5. Each feed loads "
            "<span style='color:#79c0ff;'>hole_positions_cam0.json</span> … "
            "<span style='color:#79c0ff;'>hole_positions_cam5.json</span> from your manifold folder "
            "(the number matches the USB index).<br><br>"
            "Those files stay on disk until you save new circles in the calibration tool (press "
            "<b>s</b> in that window)."
        )
        cvl.addWidget(explain)
        bl.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        actions = QHBoxLayout()
        actions.setSpacing(14)
        actions.addStretch(1)
        btn_cal = QPushButton("Calibrate ROIs")
        btn_cal.setObjectName("pageSecondary")
        btn_cal.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cal.setMinimumWidth(200)
        btn_cal.clicked.connect(self.sig_calibrate.emit)
        btn_go = QPushButton("Continue to live view")
        btn_go.setObjectName("pagePrimary")
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.setMinimumWidth(200)
        btn_go.clicked.connect(self.sig_continue.emit)
        actions.addWidget(btn_cal)
        actions.addWidget(btn_go)
        actions.addStretch(1)
        bl.addLayout(actions)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_back = QPushButton("Back")
        btn_back.setObjectName("pageGhost")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.clicked.connect(self.sig_back.emit)
        btn_row.addWidget(btn_back)
        btn_row.addStretch()
        bl.addLayout(btn_row)

        bl.addStretch(2)
        layout.addWidget(body, stretch=1)


class ManifoldSelectionPage(QWidget):
    """Initial landing page to select the manifold model."""
    sig_manifold_selected = pyqtSignal(str)
    sig_back = pyqtSignal()
    sig_add_manifold = pyqtSignal()

    def __init__(self, config_dir: str, project_root: str, parent=None):
        super().__init__(parent)
        self._config_dir = os.path.abspath(config_dir)
        self._project_root = project_root
        self.setObjectName("manifoldSelectionPage")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("brandStrip")
        header.setFixedHeight(120)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(48, 24, 48, 22)
        header_layout.setSpacing(6)

        kicker = QLabel("MANIFOLD")
        kicker.setObjectName("pageKicker")
        kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl = QLabel("Select configuration")
        title_lbl.setObjectName("pageTitleMain")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl = QLabel("Blob · laser connectivity inspection")
        sub_lbl.setObjectName("pageSubtitle")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(kicker)
        header_layout.addWidget(title_lbl)
        header_layout.addWidget(sub_lbl)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(20)
        body_layout.setContentsMargins(48, 24, 48, 32)
        body_layout.addStretch(1)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMinimumWidth(440)
        card.setMaximumWidth(520)
        c_in = QVBoxLayout(card)
        c_in.setContentsMargins(24, 24, 24, 24)
        c_in.setSpacing(14)
        fld = QLabel("Manifold model")
        fld.setObjectName("formLabel")
        fld.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.combo_manifold = QComboBox()
        self.combo_manifold.setObjectName("pageCombo")
        self.combo_manifold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.combo_manifold.setMinimumWidth(360)
        c_in.addWidget(fld)
        c_in.addWidget(self.combo_manifold)
        self.btn_add_manifold = QPushButton("Add new manifold…")
        self.btn_add_manifold.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add_manifold.setObjectName("pageSecondary")
        self.btn_add_manifold.clicked.connect(self.sig_add_manifold.emit)
        c_in.addWidget(self.btn_add_manifold)
        body_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        poc_note = QLabel(
            "Creates a config folder on disk, copies connectivity rules from a template, "
            "and adds empty ROI files per face. Some list entries can still share one folder (see manifolds_registry.json)."
        )
        poc_note.setWordWrap(True)
        poc_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        poc_note.setObjectName("pageHint")
        poc_note.setMinimumWidth(400)
        poc_note.setMaximumWidth(520)
        poc_note.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_layout.addWidget(poc_note, alignment=Qt.AlignmentFlag.AlignCenter)

        self.btn_start = QPushButton("Continue")
        self.btn_start.setObjectName("pagePrimary")
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setMinimumWidth(280)
        self.btn_start.clicked.connect(lambda: self.sig_manifold_selected.emit(self.combo_manifold.currentText()))
        body_layout.addWidget(self.btn_start, alignment=Qt.AlignmentFlag.AlignCenter)

        back_row = QHBoxLayout()
        back_row.addStretch()
        btn_back = QPushButton("Back")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setObjectName("pageGhost")
        btn_back.clicked.connect(self.sig_back.emit)
        back_row.addWidget(btn_back)
        back_row.addStretch()
        body_layout.addLayout(back_row)

        info_lbl = QLabel("Six camera faces (A–F) when all USB feeds are enabled")
        info_lbl.setObjectName("pageMeta")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(info_lbl)

        body_layout.addStretch(2)
        layout.addWidget(body, stretch=1)

    def set_manifold_items(self, labels: List[str], select: Optional[str] = None) -> None:
        cur = self.combo_manifold.currentText()
        self.combo_manifold.clear()
        for L in labels:
            self.combo_manifold.addItem(L)
        if select and self.combo_manifold.findText(select) >= 0:
            self.combo_manifold.setCurrentText(select)
        elif cur and self.combo_manifold.findText(cur) >= 0:
            self.combo_manifold.setCurrentText(cur)
        elif self.combo_manifold.count() > 0:
            self.combo_manifold.setCurrentIndex(0)


class ModeSelectionPage(QWidget):
    """Second landing page for mode selection."""
    sig_mode_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modeSelectionPage")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("brandStrip")
        header.setFixedHeight(120)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(48, 24, 48, 22)
        header_layout.setSpacing(6)

        kicker = QLabel("BLOB")
        kicker.setObjectName("pageKicker")
        kicker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl = QLabel("Inspection mode")
        title_lbl.setObjectName("pageTitleMain")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl = QLabel("Choose how you want to run the session")
        sub_lbl.setObjectName("pageSubtitle")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(kicker)
        header_layout.addWidget(title_lbl)
        header_layout.addWidget(sub_lbl)
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(24)
        body_layout.setContentsMargins(48, 20, 48, 32)
        body_layout.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(24)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        seq_card = QFrame()
        seq_card.setObjectName("modeCard")
        seq_card.setMinimumWidth(300)
        seq_card.setMaximumWidth(360)
        seq_l = QVBoxLayout(seq_card)
        seq_l.setContentsMargins(22, 22, 22, 22)
        seq_l.setSpacing(12)
        self.btn_sequential = QPushButton("Sequential")
        self.btn_sequential.setObjectName("modeActionSeq")
        self.btn_sequential.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sequential.clicked.connect(lambda: self.sig_mode_selected.emit("sequential"))
        seq_desc = QLabel(
            "Run the full guided sequence. The app advances step by step and tells you which hole to use for the laser."
        )
        seq_desc.setObjectName("pageHint")
        seq_desc.setWordWrap(True)
        seq_desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        seq_desc.setMinimumWidth(248)
        seq_desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        seq_l.addWidget(self.btn_sequential)
        seq_l.addWidget(seq_desc)

        cust_card = QFrame()
        cust_card.setObjectName("modeCard")
        cust_card.setMinimumWidth(300)
        cust_card.setMaximumWidth(360)
        cust_l = QVBoxLayout(cust_card)
        cust_l.setContentsMargins(22, 22, 22, 22)
        cust_l.setSpacing(12)
        self.btn_custom = QPushButton("Manual (single rule)")
        self.btn_custom.setObjectName("modeActionManual")
        self.btn_custom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_custom.clicked.connect(lambda: self.sig_mode_selected.emit("custom"))
        cust_desc = QLabel(
            "Choose manifold, face, and one rule. Run a single guided check using the same laser flow as sequential."
        )
        cust_desc.setObjectName("pageHint")
        cust_desc.setWordWrap(True)
        cust_desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        cust_desc.setMinimumWidth(248)
        cust_desc.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        cust_l.addWidget(self.btn_custom)
        cust_l.addWidget(cust_desc)

        btn_row.addWidget(seq_card)
        btn_row.addWidget(cust_card)
        body_layout.addLayout(btn_row)

        info_lbl = QLabel("Six camera faces (A–F) when all USB feeds are enabled")
        info_lbl.setObjectName("pageMeta")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(info_lbl)

        body_layout.addStretch(2)
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
                 cameras: Optional[List[Dict[str, Any]]] = None,
                 config_dir: Optional[str] = None,
                 project_root: Optional[str] = None,
                 cameras_file: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("Blob — Manifold inspection")
        self.setMinimumSize(1200, 720)
        self.resize(1440, 860)
        self.setStyleSheet(DARK_STYLESHEET)

        self.config_dir = config_dir or ""
        self.project_root = project_root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cameras_file = cameras_file or ""
        self._cameras_list: List[Dict[str, Any]] = list(cameras) if cameras else []

        # Face → USB index mapping (merge file so disabled faces still show correct USB if present)
        self._face_to_index: Dict[str, int] = {}
        if cameras:
            for c in cameras:
                if c.get("face") and c.get("usb_index") is not None:
                    self._face_to_index[c["face"]] = c["usb_index"]
        if self.cameras_file and os.path.isfile(self.cameras_file):
            try:
                with open(self.cameras_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for c in data.get("cameras", []):
                    if c.get("face") is not None and c.get("usb_index") is not None:
                        self._face_to_index[str(c["face"])] = int(c["usb_index"])
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                pass
        if not self._face_to_index:
            try:
                p = os.path.join("config", "cameras.json")
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    for c in data.get("cameras", []):
                        if c.get("face") is not None and c.get("usb_index") is not None:
                            self._face_to_index[str(c["face"])] = int(c["usb_index"])
            except Exception:
                pass

        self._rule_ids: list = []
        self._guided_sequence: List[Dict] = []
        self._current_step_index: int = 0

        self.selected_manifold = None
        self.selected_mode = None
        self.custom_rule_id: Optional[str] = None
        self._prep_back_target: int = 1  # stacked index: 1 = manifold, 2 = manual setup
        self._setup_event_loop = None  # QEventLoop — quit if window closed during setup (avoids hang)

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

        self.header_status = QLabel("Stopped")
        self.header_status.setObjectName("headerStatus")
        self.header_status.setStyleSheet(
            "background-color: #484f58; color: #fff; font-weight: 600; "
            "padding: 4px 12px; border-radius: 999px; font-size: 11px;"
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
        self.manifold_page = ManifoldSelectionPage(self.config_dir, self.project_root, self)
        self.manifold_page.sig_manifold_selected.connect(self._on_manifold_selected)
        self.manifold_page.sig_back.connect(self._on_manifold_back)
        self.manifold_page.sig_add_manifold.connect(self._on_add_manifold)
        self.stacked_widget.addWidget(self.manifold_page)

        # Stack 2: Manual mode — manifold / face / rule dropdowns
        self.manual_setup_page = ManualInspectionSetupPage(self.project_root, self.config_dir, self)
        self.manual_setup_page.sig_continue.connect(self._on_manual_setup_continue)
        self.manual_setup_page.sig_back.connect(self._on_manual_setup_back)
        self.stacked_widget.addWidget(self.manual_setup_page)

        _mlabels = manifold_labels(self.config_dir)
        self.manifold_page.set_manifold_items(_mlabels)
        self.manual_setup_page.set_manifold_items(_mlabels)

        # Stack 3: Pre-inspection (calibrate ROIs, then continue)
        self.prep_page = PreInspectionSetupPage(self)
        self.prep_page.sig_continue.connect(self._on_prep_continue)
        self.prep_page.sig_back.connect(self._on_prep_back)
        self.prep_page.sig_calibrate.connect(self._on_prep_calibrate)
        self.stacked_widget.addWidget(self.prep_page)

        # Stack 4: Live Dashboard
        self.dashboard_page = QWidget()
        self.stacked_widget.addWidget(self.dashboard_page)

        root = QVBoxLayout(self.dashboard_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Control bar ──
        ctrl_bar = QFrame()
        ctrl_bar.setObjectName("controlBar")
        ctrl_bar.setFixedHeight(48)
        cl = QHBoxLayout(ctrl_bar)
        cl.setContentsMargins(16, 8, 16, 8)
        cl.setSpacing(10)

        self.btn_start  = self._make_btn("▶  START",   "btnStart",  self._on_start)
        self.btn_stop   = self._make_btn("■  STOP",    "btnStop",   self._on_stop,   enabled=False)
        self.btn_pause  = self._make_btn("⏸  PAUSE",   "btnPause",  self._on_pause,  enabled=False)
        self.btn_resume = self._make_btn("⏵  RESUME",  "btnResume", self._on_resume, enabled=False)
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_resume):
            cl.addWidget(b)

        cl.addSpacing(12)
        self.btn_override = self._make_btn("✎  OVERRIDE", "btnOverride", self._on_override, enabled=False)
        cl.addWidget(self.btn_override)

        cl.addSpacing(8)
        self.btn_usb_map = self._make_btn("USB map", "btnSetup", self._on_usb_map, enabled=bool(self.cameras_file))
        self.btn_calibrate = self._make_btn("Calibrate ROIs", "btnSetup", self._on_calibrate_rois, enabled=True)
        cl.addWidget(self.btn_usb_map)
        cl.addWidget(self.btn_calibrate)

        cl.addStretch()

        self.state_lbl = QLabel("Stopped")
        self.state_lbl.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 600; letter-spacing: 0.04em;")
        cl.addWidget(self.state_lbl)
        root.addWidget(ctrl_bar)

        # ── Body: 3 columns ──
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)

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
        self.hero_frame.setObjectName("heroCameraShell")
        self.hero_layout = QVBoxLayout(self.hero_frame)
        self.hero_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.hero_frame, stretch=6) # 60% height

        # 2. Thumbnails Section (Bottom, grid)
        self.thumb_frame = QFrame()
        self.thumb_frame.setStyleSheet("background: transparent;")
        self.thumb_layout = QGridLayout(self.thumb_frame)
        self.thumb_layout.setContentsMargins(0, 0, 0, 0)
        self.thumb_layout.setSpacing(8)
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
        footer.setFixedHeight(40)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 8, 16, 8)
        fl.setSpacing(12)

        prog_lbl = QLabel("Progress")
        prog_lbl.setObjectName("pageMeta")
        fl.addWidget(prog_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(total_rules, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m steps")
        self.progress_bar.setFixedHeight(22)
        fl.addWidget(self.progress_bar, stretch=1)
        root.addWidget(footer)

        # ── Global app footer (all stack pages) ──
        app_footer = QFrame()
        app_footer.setStyleSheet("background-color: #0d1117; border-top: 1px solid #21262d;")
        app_footer.setFixedHeight(36)
        footer_layout = QHBoxLayout(app_footer)
        footer_layout.setContentsMargins(24, 0, 24, 0)
        ver_lbl = QLabel("Blob · manifold laser inspection")
        ver_lbl.setObjectName("pageMeta")
        footer_layout.addWidget(ver_lbl)
        footer_layout.addStretch()
        global_layout.addWidget(app_footer)

        # ── Clock timer ──
        self._clock = QTimer(self)
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
        if self.selected_mode == "custom":
            self.custom_rule_id = None
            self.manual_setup_page.set_initial_manifold(manifold)
            self.manual_setup_page.reload_from_disk()
            self.stacked_widget.setCurrentIndex(2)
        else:
            self.custom_rule_id = None
            self._prep_back_target = 1
            self.stacked_widget.setCurrentIndex(3)

    def _on_manifold_back(self):
        self.stacked_widget.setCurrentIndex(0)

    def _on_add_manifold(self):
        if AddManifoldDialog is None:
            return
        cf = self.cameras_file or os.path.join(self.config_dir or "", "cameras.json")
        dlg = AddManifoldDialog(
            self.config_dir or os.path.join(self.project_root, "config"),
            self.project_root,
            cf,
            DARK_STYLESHEET,
            self,
        )
        dlg.exec()
        if dlg.created_label:
            self.refresh_manifold_labels(dlg.created_label)

    def refresh_manifold_labels(self, select: Optional[str] = None) -> None:
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        labels = manifold_labels(cdir)
        self.manifold_page.set_manifold_items(labels, select)
        self.manual_setup_page.set_manifold_items(labels)

    def _on_manual_setup_back(self):
        self.stacked_widget.setCurrentIndex(1)

    def _on_manual_setup_continue(self):
        rid = self.manual_setup_page.get_rule_id()
        if not rid:
            return
        self.custom_rule_id = rid
        self.selected_manifold = self.manual_setup_page.get_manifold()
        self._prep_back_target = 2
        self.stacked_widget.setCurrentIndex(3)

    def _on_prep_continue(self):
        m = (self.selected_manifold or "").strip()
        if not m:
            QMessageBox.warning(
                self,
                "Manifold",
                "Select a manifold before continuing to live inspection.",
            )
            return
        self._enter_live_dashboard(m)

    def _on_prep_back(self):
        self.stacked_widget.setCurrentIndex(self._prep_back_target)

    def _on_prep_calibrate(self):
        self._open_calibrate_roi_dialog()

    def _all_camera_configs(self) -> List[Dict[str, Any]]:
        """Full cameras.json list (includes disabled entries) for ROI calibration."""
        if self.cameras_file and os.path.isfile(self.cameras_file):
            try:
                with open(self.cameras_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return list(data.get("cameras", []))
            except (json.JSONDecodeError, OSError):
                pass
        return list(self._cameras_list)

    def _open_calibrate_roi_dialog(self):
        if not HAS_PYQT6 or CalibrateRoiDialog is None:
            return
        from config_loader import manifold_data_subdirectory

        manifold = (self.selected_manifold or "").strip()
        if not manifold:
            QMessageBox.warning(
                self,
                "Manifold",
                "Select a manifold before calibrating ROIs.",
            )
            return
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        sub = manifold_data_subdirectory(manifold, cdir)
        dlg = CalibrateRoiDialog(
            self._all_camera_configs(),
            manifold,
            cdir,
            self.project_root,
            DARK_STYLESHEET,
            data_subdir=sub,
            parent=self,
        )
        dlg.exec()

    def _enter_live_dashboard(self, manifold: str):
        self.selected_manifold = manifold
        self.stacked_widget.setCurrentIndex(4)
        self.global_header.show()
        self.header_status.show()
        self.clock_lbl.show()
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()  # Paint dashboard before main.py continues
        self.sig_manifold_selected.emit(manifold)

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
        denom = max(total, 1)
        self.progress_bar.setRange(0, denom)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"%v / {denom} steps")
        if sequence:
            self._current_step_index = 0
            self.step_list.set_active(0)
            self.instruction_panel.show_step(sequence[0], total)
        else:
            self._current_step_index = 0
            self.instruction_panel.status_lbl.setText("No guided steps")
            self.instruction_panel.status_lbl.setStyleSheet(
                "color: #d29922; font-size: 18px; font-weight: bold;"
            )
            self.instruction_panel.face_hole_lbl.setText(
                "Check connectivity rules and camera availability, or use manual mode."
            )

    def set_setup_event_loop(self, loop) -> None:
        """While waiting for manifold selection, closing the window quits this loop (see closeEvent)."""
        self._setup_event_loop = loop

    def closeEvent(self, event: QCloseEvent):
        from PyQt6.QtCore import QEventLoop, QTimer

        loop = getattr(self, "_setup_event_loop", None)
        if loop is not None and isinstance(loop, QEventLoop) and loop.isRunning():
            QTimer.singleShot(0, loop.quit)
        super().closeEvent(event)

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
            
            # Update target labels on camera widgets
            input_hole = step.get('input_hole', '')
            expected_outputs = step.get('expected_outputs', [])
            
            # Clear all target labels first
            for cw in self.camera_widgets.values():
                cw.set_target_label(None)
            
            # Set target on input face camera
            if input_face and input_hole:
                input_cw = self.camera_widgets.get(f"CAM_{input_face}")
                if input_cw:
                    input_cw.set_target_label(f"INSERT → {input_hole}")
            
            # Set expected output targets on their cameras
            for out in expected_outputs:
                out_face = out.get('face', '')
                out_hole = out.get('hole_id', '')
                if out_face and out_hole:
                    out_cw = self.camera_widgets.get(f"CAM_{out_face}")
                    if out_cw:
                        out_cw.set_target_label(f"EXPECT → {out_hole}")

    def update_step_result(self, step_index: int, passed: bool):
        if step_index < 0 or not self._guided_sequence or step_index >= len(self._guided_sequence):
            return
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
        pill = "font-weight: 600; padding: 4px 12px; border-radius: 999px; font-size: 11px;"
        if res == 'FAIL':
            self.header_status.setText("Fail detected")
            self.header_status.setStyleSheet(
                "background-color: #da3633; color: #fff; " + pill
            )
        elif res == 'PASS':
            self.header_status.setText("Running")
            self.header_status.setStyleSheet(
                "background-color: #238636; color: #fff; " + pill
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
        self.state_lbl.setText("Running")
        self.header_status.setText("Running")
        self.header_status.setStyleSheet(
            "background-color: #238636; color: #fff; font-weight: 600; "
            "padding: 4px 12px; border-radius: 999px; font-size: 11px;"
        )

    def _on_stop(self):
        self.sig_stop.emit()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(False)
        self.state_lbl.setText("Stopped")
        self.header_status.setText("Stopped")
        self.header_status.setStyleSheet(
            "background-color: #484f58; color: #fff; font-weight: 600; "
            "padding: 4px 12px; border-radius: 999px; font-size: 11px;"
        )

    def _on_pause(self):
        self.sig_pause.emit()
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)
        self.state_lbl.setText("Paused")
        self.header_status.setText("Paused")
        self.header_status.setStyleSheet(
            "background-color: #9e6a03; color: #fff; font-weight: 600; "
            "padding: 4px 12px; border-radius: 999px; font-size: 11px;"
        )

    def _on_resume(self):
        self.sig_resume.emit()
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.state_lbl.setText("Running")
        self.header_status.setText("Running")
        self.header_status.setStyleSheet(
            "background-color: #238636; color: #fff; font-weight: 600; "
            "padding: 4px 12px; border-radius: 999px; font-size: 11px;"
        )

    def _on_override(self):
        if not self._rule_ids:
            return
        dlg = OverrideDialog(self._rule_ids, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rule_id, result = dlg.get_selection()
            self.sig_override.emit(rule_id, result)

    def _on_usb_map(self):
        if not HAS_PYQT6 or CameraSetupDialog is None or not self.cameras_file:
            return
        dlg = CameraSetupDialog(self.cameras_file, DARK_STYLESHEET, self)
        dlg.exec()

    def _on_calibrate_rois(self):
        self._open_calibrate_roi_dialog()


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
                     cameras=None,
                     config_dir: Optional[str] = None,
                     project_root: Optional[str] = None,
                     cameras_file: Optional[str] = None):
    """
    Returns (dashboard, qt_app_or_None).
    If PyQt6 is available and force_cv is False, returns a DashboardWindow.
    Otherwise returns an OpenCVDashboard.
    """
    if HAS_PYQT6 and not force_cv:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setStyleSheet(DARK_STYLESHEET)
        base_font = QFont()
        base_font.setPointSize(10)
        base_font.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(base_font)
        win = DashboardWindow(
            total_rules=total_rules,
            cameras=cameras,
            config_dir=config_dir,
            project_root=project_root,
            cameras_file=cameras_file,
        )
        win.show()
        return win, app
    else:
        return OpenCVDashboard(total_rules=total_rules, cameras=cameras), None

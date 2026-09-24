"""
Operator Dashboard — PyQt6  (Guided Inspection Mode)

Stacked pages (QStackedWidget indices):
  0 — Start: Sequential vs Manual. Redo camera setup is a link here.
  1 — Manifold: DALIA / Manifold 2 / Manifold 3 (sequential, multiple models)
  2 — Manual setup only: dropdowns for manifold, input face, rule
  3 — Camera setup once: assign faces, place hole ROIs, hole connections (no PIN)
  4 — Live dashboard (cameras, START/STOP). Setup is not on this bar.

Daily path after setup is saved: Start → (manifold if more than one) → live → wait for cameras → START.
First time, and whenever Redo camera setup was clicked: manifold → assign faces → optional ROIs and hole connections → Continue.
OVERRIDE stays on the live bar. There is no Admin and no PIN.

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
import sys
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Set

from logic_engine import rule_has_unavailable_output
from config_loader import (
    manifold_labels,
    manifold_folder_for_label,
    load_last_manifold,
    mark_setup_complete,
    save_last_manifold,
    setup_is_complete,
)

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
    from PyQt6.QtCore import Qt, QTimer, pyqtSignal, qInstallMessageHandler
    from PyQt6.QtGui import QImage, QPixmap, QFont, QColor, QPalette, QCloseEvent
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False
    print("[Dashboard] PyQt6 not installed. Install with: pip install PyQt6")

if HAS_PYQT6:
    try:
        from camera_setup_ui import FaceAssignWizardDialog
        from manifold_setup_ui import AddManifoldDialog
        from session_overlay import SessionBusyOverlay
        from roi_editor import RoiEditorDialog
    except ImportError:
        FaceAssignWizardDialog = None  # type: ignore
        AddManifoldDialog = None  # type: ignore
        SessionBusyOverlay = None  # type: ignore
        RoiEditorDialog = None  # type: ignore
    try:
        from rule_editor_ui import RuleEditorDialog
    except ImportError:
        RuleEditorDialog = None  # type: ignore
else:
    FaceAssignWizardDialog = None  # type: ignore
    AddManifoldDialog = None  # type: ignore
    SessionBusyOverlay = None  # type: ignore
    RoiEditorDialog = None  # type: ignore
    RuleEditorDialog = None  # type: ignore


# ──────────────────────────────────────────────
# STYLESHEET — Godrej Aerospace light paper shell
# ──────────────────────────────────────────────

SHELL_ORG = "Godrej Aerospace"
SHELL_PLANT = "Plant name"
SHELL_DEPT = "Department name"
SHELL_APP = "Manifold inspection"

PAGE_KICKERS = {
    0: "Sequential cell",
    1: "Select configuration",
    2: "Manual inspection",
    3: "Camera setup",
    4: "Live inspection",
}

# Paper #fafaf7  panel #ffffff  line #d8d3c8  ink #0f1216  muted #5c6158
# plum #810055  navy #0e2742  good #2f6b45  warn #8a5a12  bad #9b2e22
APP_STYLESHEET = """
/* ── Base ── */
QMainWindow, QWidget {
    background-color: #fafaf7;
    color: #0f1216;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 10pt;
}
QLabel { color: #0f1216; }

/* ── Wizard / setup pages (shared) ── */
QFrame#brandStrip, QFrame#headerBar {
    background-color: #ffffff;
    border: none;
    border-bottom: 1px solid #d8d3c8;
}
QLabel#brandMarkFallback {
    color: #810055;
    font-size: 18px;
    font-weight: 600;
}
QLabel#brandOrg {
    color: #0e2742;
    font-size: 13px;
    font-weight: 600;
}
QLabel#brandContext {
    color: #5c6158;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.12em;
}
QLabel#pageKicker, QLabel#headerKicker {
    color: #810055;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 0.16em;
}
QLabel#pageTitleMain {
    color: #0e2742;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
}
QLabel#headerTitle {
    color: #0e2742;
    font-size: 22px;
    font-weight: 600;
    letter-spacing: -0.02em;
}
QLabel#pageSectionTitle {
    color: #0e2742;
    font-size: 16px;
    font-weight: 600;
}
QLabel#pageSubtitle {
    color: #5c6158;
    font-size: 13px;
    font-weight: normal;
}
QLabel#pageHint {
    color: #5c6158;
    font-size: 13px;
    line-height: 1.5;
}
QLabel#pageMeta {
    color: #5c6158;
    font-size: 12px;
}
QLabel#formLabel {
    color: #5c6158;
    font-size: 12px;
    font-weight: 500;
    min-width: 120px;
}
QFrame#formCard, QFrame#modeCard {
    background-color: #ffffff;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}
QPushButton {
    background-color: #fafaf7;
    color: #0e2742;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 16px;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}
QPushButton:hover { background-color: #f3f1ea; }
QPushButton:disabled { color: #8a8580; background-color: #f3f1ea; }
QPushButton#modeActionSeq, QPushButton#pagePrimary {
    background-color: #810055;
    color: #ffffff;
    font-weight: 600;
    font-size: 15px;
    padding: 12px 16px;
    border: 1px solid #810055;
    border-radius: 4px;
    min-height: 48px;
}
QPushButton#modeActionSeq:hover, QPushButton#pagePrimary:hover { background-color: #6b0047; border-color: #6b0047; }
QPushButton#modeActionSeq:pressed, QPushButton#pagePrimary:pressed { background-color: #6b0047; }
QPushButton#modeActionManual, QPushButton#pageSecondary {
    background-color: #fafaf7;
    color: #0e2742;
    font-weight: 600;
    font-size: 15px;
    padding: 12px 16px;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    min-height: 48px;
    min-width: 240px;
}
QPushButton#modeActionManual:hover, QPushButton#pageSecondary:hover {
    background-color: #ffffff;
    border-color: #810055;
    color: #0e2742;
}
QPushButton#pagePrimary { min-width: 200px; padding: 12px 24px; }
QPushButton#pageGhost {
    background-color: transparent;
    color: #0e2742;
    font-weight: 500;
    font-size: 13px;
    padding: 8px 16px;
    border: 1px solid transparent;
    border-radius: 4px;
}
QPushButton#pageGhost:hover {
    color: #0e2742;
    background-color: #f3f1ea;
}
QPushButton#pageGhost:focus { border: 1px solid transparent; outline: none; }
QPushButton#pageLink {
    background-color: #fafaf7;
    color: #810055;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 16px;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}
QPushButton#pageLink:hover { background-color: #f3f1ea; border-color: #810055; }

QComboBox#pageCombo {
    background-color: #ffffff;
    color: #0f1216;
    font-weight: 500;
    font-size: 15px;
    padding: 12px 16px;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    min-height: 24px;
    min-width: 280px;
}
QComboBox#pageCombo:hover { border-color: #8a8580; }
QComboBox#pageCombo:focus { border-color: #810055; }
QComboBox#pageCombo::drop-down { border: none; width: 28px; }
QComboBox#pageCombo QAbstractItemView {
    background-color: #ffffff;
    color: #0f1216;
    font-size: 14px;
    selection-background-color: #810055;
    selection-color: #ffffff;
    border: 1px solid #d8d3c8;
    padding: 4px;
}

QLabel#headerClock { color: #5c6158; font-size: 12px; }
QLabel#headerStatus {
    font-size: 11px;
    font-weight: 600;
    padding: 4px 8px;
    border-radius: 4px;
    border: 1px solid #d8d3c8;
}

QFrame#controlBar, QFrame#footerBar, QFrame#appFooter {
    background-color: #ffffff;
    border: none;
}
QFrame#controlBar { border-bottom: 1px solid #d8d3c8; }
QFrame#footerBar, QFrame#appFooter { border-top: 1px solid #d8d3c8; }
QPushButton#btnStart {
    background-color: #2f6b45;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 16px;
    border: 1px solid #2f6b45;
    border-radius: 4px;
    min-height: 28px;
}
QPushButton#btnStart:hover  { background-color: #275a3a; }
QPushButton#btnStart:disabled { background-color: #f3f1ea; color: #8a8580; border-color: #d8d3c8; }
QPushButton#btnStop {
    background-color: #9b2e22;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 16px;
    border: 1px solid #9b2e22;
    border-radius: 4px;
    min-height: 28px;
}
QPushButton#btnStop:hover  { background-color: #7f251c; }
QPushButton#btnStop:disabled { background-color: #f3f1ea; color: #8a8580; border-color: #d8d3c8; }
QPushButton#btnPause {
    background-color: #8a5a12;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 16px;
    border: 1px solid #8a5a12;
    border-radius: 4px;
    min-height: 28px;
}
QPushButton#btnPause:hover  { background-color: #734b0f; }
QPushButton#btnPause:disabled { background-color: #f3f1ea; color: #8a8580; border-color: #d8d3c8; }
QPushButton#btnResume {
    background-color: #810055;
    color: #fff;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 16px;
    border: 1px solid #810055;
    border-radius: 4px;
    min-height: 28px;
}
QPushButton#btnResume:hover  { background-color: #6b0047; }
QPushButton#btnResume:disabled { background-color: #f3f1ea; color: #8a8580; border-color: #d8d3c8; }
QPushButton#btnOverride, QPushButton#btnSetup {
    background-color: #fafaf7;
    color: #0e2742;
    font-weight: 600;
    font-size: 12px;
    padding: 8px 16px;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    min-height: 28px;
}
QPushButton#btnOverride:hover, QPushButton#btnSetup:hover { background-color: #ffffff; border-color: #810055; }
QPushButton#btnOverride:disabled, QPushButton#btnSetup:disabled {
    background-color: #f3f1ea; color: #8a8580; border-color: #d8d3c8;
}

QFrame#cameraCell {
    background-color: #ffffff;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}
QFrame#cameraVideoShell, QFrame#heroCameraShell {
    background-color: #f3f1ea;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}

QFrame#stepListPanel, QFrame#instructionPanel {
    background-color: #ffffff;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
}

QProgressBar {
    background-color: #f3f1ea;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    text-align: center;
    color: #0f1216;
    font-weight: 600;
    font-size: 11px;
    height: 22px;
}
QProgressBar::chunk {
    background-color: #2f6b45;
    border-radius: 4px;
    margin: 1px;
}

QDialog { background-color: #fafaf7; color: #0f1216; }
QComboBox {
    background-color: #ffffff;
    color: #0f1216;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 13px;
    min-height: 20px;
}
QComboBox:hover { border-color: #8a8580; }
QComboBox:focus { border-color: #810055; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #0f1216;
    selection-background-color: #810055;
    selection-color: #ffffff;
    border: 1px solid #d8d3c8;
}
QRadioButton { color: #0f1216; font-size: 13px; spacing: 8px; }
QCheckBox { color: #0f1216; }
QLineEdit, QTextEdit, QTableWidget, QSpinBox {
    background-color: #ffffff;
    color: #0f1216;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    selection-background-color: #810055;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #f3f1ea;
    color: #0e2742;
    border: none;
    border-bottom: 1px solid #d8d3c8;
    padding: 8px 8px;
    font-weight: 600;
}
QGroupBox {
    color: #0e2742;
    border: 1px solid #d8d3c8;
    border-radius: 4px;
    margin-top: 12px;
    padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QScrollArea { background: #ffffff; border: 1px solid #d8d3c8; border-radius: 4px; }

QScrollBar:vertical {
    background: #fafaf7;
    width: 10px;
    margin: 0;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #d8d3c8;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #8a8580; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QLabel#stepPanelTitle {
    color: #810055;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.07em;
    padding: 12px 12px 8px 12px;
    border-bottom: 1px solid #d8d3c8;
    background-color: transparent;
}
QWidget#sessionBusyOverlay { background-color: rgba(14, 39, 66, 90); }
"""

def _godrej_logo_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, "..", "assets", "godrej-logo.png"))
    return path if os.path.isfile(path) else ""


def _status_pill_qss(kind: str) -> str:
    kinds = {
        "stopped": ("#fafaf7", "#5c6158", "#d8d3c8"),
        "running": ("#2f6b45", "#ffffff", "#2f6b45"),
        "paused": ("#8a5a12", "#ffffff", "#8a5a12"),
        "fail": ("#9b2e22", "#ffffff", "#9b2e22"),
    }
    bg, fg, bd = kinds.get(kind, kinds["stopped"])
    return (
        f"background-color: {bg}; color: {fg}; border: 1px solid {bd}; "
        "font-weight: 600; padding: 4px 8px; border-radius: 4px; font-size: 11px;"
    )


def _attach_godrej_logo(target: QLabel, fallback: QLabel) -> None:
    path = _godrej_logo_path()
    pix = QPixmap(path) if path else QPixmap()
    if pix.isNull():
        target.hide()
        fallback.show()
        return
    scaled = pix.scaledToHeight(32, Qt.TransformationMode.SmoothTransformation)
    target.setPixmap(scaled)
    target.setFixedSize(scaled.size())
    target.show()
    fallback.hide()



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
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.feed_label = QLabel()
        self.feed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.feed_label.setMinimumSize(120, 90)
        label_text = f"USB {usb_index} · Face {face}" if usb_index is not None else f"Face {face}"
        self.feed_label.setText(f"{label_text}\nNO SIGNAL")
        self.feed_label.setStyleSheet(
            "background-color: transparent; border-radius: 4px; "
            "color: #5c6158; font-size: 11px; font-weight: 600;"
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
            "background-color: rgba(255,255,255,230); color: #0e2742; "
            "font-weight: 600; font-size: 10px; padding: 4px 8px; border-radius: 4px;"
        )
        self._face_lbl.adjustSize()
        self._face_lbl.move(6, 6)

        self._fps_lbl = QLabel("-- fps", self)
        self._fps_lbl.setStyleSheet(
            "background-color: rgba(255,255,255,220); color: #5c6158; "
            "font-size: 10px; padding: 4px 8px; border-radius: 4px;"
        )
        self._fps_lbl.adjustSize()
        self._fps_lbl.move(6, 6 + self._face_lbl.height() + 4)

        # Target hole overlay (shown when this camera is inspecting a specific hole)
        self._target_lbl = QLabel("", self)
        self._target_lbl.setStyleSheet(
            "background-color: rgba(138,90,18,220); color: #ffffff; "
            "font-weight: 700; font-size: 11px; padding: 4px 8px; border-radius: 4px;"
        )
        self._target_lbl.hide()

    def set_usb_index(self, usb_index: Optional[int], assigned: bool = True) -> None:
        """Refresh the Face/USB chrome after assignment (labels are stale if set only at init)."""
        if not assigned:
            text = f"Face {self.face} · not assigned"
        elif usb_index is not None:
            text = f"USB {usb_index} · Face {self.face}"
        else:
            text = f"Face {self.face}"
        self._face_lbl.setText(text)
        self._face_lbl.adjustSize()
        if not assigned:
            self.feed_label.setText(f"{text}\nNO CAMERA")
            self._fps_lbl.setText("—")
            self._fps_lbl.adjustSize()

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
        fh, fw = frame.shape[:2]
        if hasattr(QImage.Format, 'Format_BGR888'):
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame)
            qimg = QImage(frame.data, fw, fh, 3 * fw, QImage.Format.Format_BGR888)
        else:
            rgb = frame[..., ::-1].copy()
            qimg = QImage(rgb.data, fw, fh, 3 * fw, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg)
        scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.feed_label.setPixmap(scaled)

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
        self._vbox.setContentsMargins(8, 4, 8, 8)
        self._vbox.setSpacing(4)
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
            row.setStyleSheet("background: transparent; border-radius: 4px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 4, 4, 4)
            rl.setSpacing(8)

            icon = QLabel("○")
            icon.setStyleSheet("color: #8a8580; font-size: 12px; min-width: 14px;")
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

            text = QLabel(f"{num:02d}.  {face} · {hole}")
            text.setStyleSheet("color: #5c6158; font-size: 11px;")

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
                prev.setStyleSheet("background: transparent; border-radius: 4px;")
                self._labels[self._current].setStyleSheet("color: #5c6158; font-size: 11px;")
                self._icons[self._current].setText("○")
                self._icons[self._current].setStyleSheet("color: #8a8580; font-size: 12px; min-width: 14px;")

        self._current = index
        if 0 <= index < len(self._frames):
            f = self._frames[index]
            f.setStyleSheet(
                "background-color: #f3f1ea; border-left: 3px solid #810055; border-radius: 4px;"
            )
            self._labels[index].setStyleSheet("color: #0e2742; font-size: 11px; font-weight: 600;")
            self._icons[index].setText("▶")
            self._icons[index].setStyleSheet("color: #810055; font-size: 12px; min-width: 14px;")
            self._scroll.ensureWidgetVisible(f)

    def mark_result(self, index: int, passed: bool):
        if not (0 <= index < len(self._frames)):
            return
        f = self._frames[index]
        f.setProperty("done", True)
        if passed:
            f.setStyleSheet("background-color: #e8f0ea; border-left: 3px solid #2f6b45; border-radius: 4px;")
            self._labels[index].setStyleSheet("color: #2f6b45; font-size: 11px;")
            self._icons[index].setText("✓")
            self._icons[index].setStyleSheet("color: #2f6b45; font-size: 12px; min-width: 14px;")
        else:
            f.setStyleSheet("background-color: #f6e8e6; border-left: 3px solid #9b2e22; border-radius: 4px;")
            self._labels[index].setStyleSheet("color: #9b2e22; font-size: 11px;")
            self._icons[index].setText("✗")
            self._icons[index].setStyleSheet("color: #9b2e22; font-size: 12px; min-width: 14px;")


# ──────────────────────────────────────────────
# InstructionPanel  (center column)
# ──────────────────────────────────────────────

class InstructionPanel(QFrame):
    """Large operator instruction: what to insert and what to expect."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("instructionPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # Step counter
        self.step_lbl = QLabel("STEP — / —")
        self.step_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.step_lbl.setStyleSheet("color: #5c6158; font-size: 13px; font-weight: bold;")
        layout.addWidget(self.step_lbl)

        _div1 = QFrame(); _div1.setFrameShape(QFrame.Shape.HLine)
        _div1.setStyleSheet("color: #d8d3c8;")
        layout.addWidget(_div1)

        # INSERT LASER INTO
        lbl_insert = QLabel("INSERT LASER INTO:")
        lbl_insert.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_insert.setStyleSheet("color: #5c6158; font-size: 13px;")
        layout.addWidget(lbl_insert)

        self.face_hole_lbl = QLabel("—")
        self.face_hole_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.face_hole_lbl.setWordWrap(True)
        self.face_hole_lbl.setStyleSheet("color: #0e2742; font-size: 30px; font-weight: bold;")
        layout.addWidget(self.face_hole_lbl)

        layout.addSpacing(8)

        # EXPECT LIGHT AT
        lbl_expect = QLabel("EXPECT LIGHT AT:")
        lbl_expect.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_expect.setStyleSheet("color: #5c6158; font-size: 13px;")
        layout.addWidget(lbl_expect)

        self._out_widget = QWidget()
        self._out_widget.setStyleSheet("background: transparent;")
        self._out_layout = QVBoxLayout(self._out_widget)
        self._out_layout.setContentsMargins(0, 0, 0, 0)
        self._out_layout.setSpacing(4)
        self._out_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._out_widget)

        layout.addStretch()

        _div2 = QFrame(); _div2.setFrameShape(QFrame.Shape.HLine)
        _div2.setStyleSheet("color: #d8d3c8;")
        layout.addWidget(_div2)

        # Status
        self.status_lbl = QLabel("⏸  WAITING")
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setStyleSheet("color: #5c6158; font-size: 22px; font-weight: bold;")
        layout.addWidget(self.status_lbl)

        # Countdown timer label (60s limit)
        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.countdown_lbl.setStyleSheet("color: #5c6158; font-size: 14px; font-weight: bold;")
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
                background-color: #d8d3c8;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #810055;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.timeout_bar)

        layout.addSpacing(8)

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
        row.setSpacing(16)
        row.addStretch()

        pc = QVBoxLayout()
        self.pass_count = QLabel("0")
        self.pass_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pass_count.setStyleSheet("color: #2f6b45; font-size: 22px; font-weight: bold;")
        pl = QLabel("PASS")
        pl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pl.setStyleSheet("color: #2f6b45; font-size: 11px; font-weight: bold;")
        pc.addWidget(self.pass_count); pc.addWidget(pl)

        fc = QVBoxLayout()
        self.fail_count = QLabel("0")
        self.fail_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fail_count.setStyleSheet("color: #9b2e22; font-size: 22px; font-weight: bold;")
        fl = QLabel("FAIL")
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.setStyleSheet("color: #9b2e22; font-size: 11px; font-weight: bold;")
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
            lbl.setStyleSheet("color: #0f1216; font-size: 13px;")
            self._out_layout.addWidget(lbl)
            self._out_labels.append(lbl)

        self.set_waiting()

    def set_waiting(self):
        self.status_lbl.setText("⏸  WAITING FOR LASER")
        self.status_lbl.setStyleSheet("color: #5c6158; font-size: 22px; font-weight: bold;")
        self.monitor_bar.hide()
        self.monitor_bar.setValue(0)
        self.countdown_lbl.setText("Time Left: 60s")
        self.countdown_lbl.setStyleSheet("color: #5c6158; font-size: 14px; font-weight: bold;")
        self.timeout_bar.show()
        self.timeout_bar.setValue(600)
        self._update_timeout_bar_color(60)

    def set_monitoring(self, pct: int = 0):
        self.status_lbl.setText("⏱  MONITORING...")
        self.status_lbl.setStyleSheet("color: #810055; font-size: 22px; font-weight: bold;")
        self.monitor_bar.show()
        self.monitor_bar.setValue(pct)

    def set_pass(self):
        self.status_lbl.setText("✓  PASS")
        self.status_lbl.setStyleSheet("color: #2f6b45; font-size: 28px; font-weight: bold;")
        self.monitor_bar.hide()
        self.timeout_bar.hide()
        self.countdown_lbl.setText("")
        self._pass_total += 1
        self.pass_count.setText(str(self._pass_total))

    def set_fail(self):
        self.status_lbl.setText("✗  FAIL")
        self.status_lbl.setStyleSheet("color: #9b2e22; font-size: 28px; font-weight: bold;")
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
            self.countdown_lbl.setStyleSheet("color: #9b2e22; font-size: 16px; font-weight: bold;")
        elif seconds_remaining <= 20:
            self.countdown_lbl.setStyleSheet("color: #8a5a12; font-size: 15px; font-weight: bold;")
        else:
            self.countdown_lbl.setStyleSheet("color: #5c6158; font-size: 14px; font-weight: bold;")

    def _update_timeout_bar_color(self, seconds: int):
        color = "#810055"
        if seconds <= 10:
            color = "#9b2e22"
        elif seconds <= 20:
            color = "#8a5a12"
            
        self.timeout_bar.setStyleSheet(f"""
            QProgressBar {{

                border: none;
                background-color: #d8d3c8;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 4px;
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
        self.setStyleSheet(APP_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        title = QLabel("Manual Inspection Override")
        title.setObjectName("pageTitleMain")
        title.setStyleSheet("color: #0e2742; font-size: 14px; font-weight: bold;")
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
        self.radio_pass.setStyleSheet("color: #2f6b45; font-weight: bold;")
        self.radio_fail = QRadioButton("FAIL")
        self.radio_fail.setStyleSheet("color: #9b2e22; font-weight: bold;")
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
            "QPushButton { background-color: #fafaf7; color: #0e2742; "
            "border: 1px solid #d8d3c8; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #f3f1ea; }"
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

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.setSpacing(24)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.addStretch(1)

        heading = QLabel("Manual inspection")
        heading.setObjectName("pageSectionTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(heading)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMaximumWidth(560)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 24, 24, 24)
        cl.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(16)
        form.setHorizontalSpacing(16)
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
    """One-time camera setup after the manifold is chosen. Cameras are still closed."""

    sig_continue = pyqtSignal()
    sig_back = pyqtSignal()
    sig_assign = pyqtSignal()
    sig_rois = pyqtSignal()
    sig_connections = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.setSpacing(16)
        bl.setContentsMargins(24, 24, 24, 24)
        bl.addStretch(1)

        heading = QLabel("Camera setup")
        heading.setObjectName("pageSectionTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(heading)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMinimumWidth(500)
        card.setMaximumWidth(580)
        cvl = QVBoxLayout(card)
        cvl.setContentsMargins(24, 24, 24, 24)
        cvl.setSpacing(12)
        explain = QLabel()
        explain.setObjectName("pageHint")
        explain.setWordWrap(True)
        explain.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        explain.setMinimumWidth(440)
        explain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        explain.setTextFormat(Qt.TextFormat.RichText)
        explain.setText(
            "1. <b>Assign camera faces</b> — look at each USB snapshot and pick Face A–F. "
            "Required once. This is the map the app uses every boot.<br><br>"
            "2. <b>Place hole ROIs</b> — freeze one face at a time. Click the freeze first so keys work. "
            "Click to drop or move; +/- width; [ ] height; arrows rotate; a add; c copy; d delete; SPACE recapture. Save. "
            "Face A writes hole_positions_cam0.json, Face B cam1, and so on. "
            "You can continue with some faces empty and come back later.<br><br>"
            "3. <b>Hole connections</b> — type the laser-in / light-out list, or load the spreadsheet "
            "(.xlsx or .csv) when you have it. That file is not in the app yet. "
            "Saving replaces connectivity rules for this manifold and keeps a backup."
        )
        cvl.addWidget(explain)
        bl.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        actions = QVBoxLayout()
        actions.setSpacing(12)
        actions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_assign = QPushButton("Assign camera faces")
        btn_assign.setObjectName("pageSecondary")
        btn_assign.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_assign.setMinimumWidth(280)
        btn_assign.clicked.connect(self.sig_assign.emit)
        btn_rois = QPushButton("Place hole ROIs")
        btn_rois.setObjectName("pageSecondary")
        btn_rois.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rois.setMinimumWidth(280)
        btn_rois.clicked.connect(self.sig_rois.emit)
        btn_rules = QPushButton("Hole connections")
        btn_rules.setObjectName("pageSecondary")
        btn_rules.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rules.setMinimumWidth(280)
        btn_rules.clicked.connect(self.sig_connections.emit)
        btn_go = QPushButton("Continue to live view")
        btn_go.setObjectName("pagePrimary")
        btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go.setMinimumWidth(280)
        btn_go.clicked.connect(self.sig_continue.emit)
        for b in (btn_assign, btn_rois, btn_rules, btn_go):
            actions.addWidget(b, alignment=Qt.AlignmentFlag.AlignCenter)
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

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(16)
        body_layout.setContentsMargins(24, 24, 24, 24)
        body_layout.addStretch(1)

        heading = QLabel("Select configuration")
        heading.setObjectName("pageSectionTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(heading)

        card = QFrame()
        card.setObjectName("formCard")
        card.setMinimumWidth(440)
        card.setMaximumWidth(520)
        c_in = QVBoxLayout(card)
        c_in.setContentsMargins(24, 24, 24, 24)
        c_in.setSpacing(12)
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
    """Start screen: Sequential or Manual. Camera setup is after the manifold."""
    sig_mode_selected = pyqtSignal(str)
    sig_redo_setup = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modeSelectionPage")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.setSpacing(24)
        body_layout.setContentsMargins(24, 24, 24, 24)
        body_layout.addStretch(1)

        heading = QLabel("Start inspection")
        heading.setObjectName("pageSectionTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(heading)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(24)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        seq_card = QFrame()
        seq_card.setObjectName("modeCard")
        seq_card.setMinimumWidth(300)
        seq_card.setMaximumWidth(360)
        seq_l = QVBoxLayout(seq_card)
        seq_l.setContentsMargins(24, 24, 24, 24)
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
        cust_l.setContentsMargins(24, 24, 24, 24)
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

        self.btn_redo = QPushButton("Redo camera setup")
        self.btn_redo.setObjectName("pageGhost")
        self.btn_redo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_redo.clicked.connect(self.sig_redo_setup.emit)
        body_layout.addWidget(self.btn_redo, alignment=Qt.AlignmentFlag.AlignCenter)

        info_lbl = QLabel("Assign faces, hole ROIs, and hole connections run once after the manifold. Use Redo to open them again.")
        info_lbl.setObjectName("pageMeta")
        info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_lbl.setWordWrap(True)
        info_lbl.setMaximumWidth(640)
        body_layout.addWidget(info_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

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
    sig_reload_rules = pyqtSignal()
    sig_return_to_setup = pyqtSignal()

    def __init__(self, total_rules: int = 0,
                 cameras: Optional[List[Dict[str, Any]]] = None,
                 config_dir: Optional[str] = None,
                 project_root: Optional[str] = None,
                 cameras_file: Optional[str] = None):
        super().__init__()
        self.setWindowTitle("Manifold inspection — Godrej Aerospace")
        self.setMinimumSize(1100, 720)
        self.resize(1440, 860)
        self.setStyleSheet(APP_STYLESHEET)

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
        self._force_setup = False
        self._setup_event_loop = None  # QEventLoop — quit if window closed during setup (avoids hang)
        self._inspect_event_loop = None
        self._handshake_active = False
        self._cameras_ready = False
        self.shutdown_requested = False
        self._roi_session_open = False
        self._comm_queues: Dict[str, Any] = {}
        self._snapshot_queue = None
        self._failed_faces: List[str] = []
        self._busy_overlay = None

        # ── Central Widget & Global Layout ──
        central = QWidget()
        self.setCentralWidget(central)
        global_layout = QVBoxLayout(central)
        global_layout.setContentsMargins(0, 0, 0, 0)
        global_layout.setSpacing(0)

        # ── Global Godrej header (every stack page) ──
        self.global_header = QFrame()
        self.global_header.setObjectName("headerBar")
        self.global_header.setMinimumHeight(80)
        hl = QHBoxLayout(self.global_header)
        hl.setContentsMargins(24, 12, 24, 12)
        hl.setSpacing(16)

        brand = QHBoxLayout()
        brand.setSpacing(12)
        self._logo_lbl = QLabel()
        self._logo_lbl.setObjectName("brandLogo")
        self._logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_fallback = QLabel("Godrej")
        self._logo_fallback.setObjectName("brandMarkFallback")
        _attach_godrej_logo(self._logo_lbl, self._logo_fallback)
        brand.addWidget(self._logo_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        brand.addWidget(self._logo_fallback, alignment=Qt.AlignmentFlag.AlignVCenter)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(4)
        org_lbl = QLabel(SHELL_ORG)
        org_lbl.setObjectName("brandOrg")
        ctx_lbl = QLabel(f"{SHELL_PLANT}  ·  {SHELL_DEPT}".upper())
        ctx_lbl.setObjectName("brandContext")
        brand_text.addWidget(org_lbl)
        brand_text.addWidget(ctx_lbl)
        brand.addLayout(brand_text)
        hl.addLayout(brand)
        hl.addStretch()

        right = QVBoxLayout()
        right.setSpacing(4)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        title_lbl = QLabel(SHELL_APP)
        title_lbl.setObjectName("headerTitle")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.header_kicker = QLabel(PAGE_KICKERS[0].upper())
        self.header_kicker.setObjectName("headerKicker")
        self.header_kicker.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(title_lbl)
        right.addWidget(self.header_kicker)
        live_meta = QHBoxLayout()
        live_meta.setSpacing(8)
        live_meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.header_status = QLabel("Stopped")
        self.header_status.setObjectName("headerStatus")
        self.header_status.setStyleSheet(_status_pill_qss("stopped"))
        self.header_status.hide()
        self.clock_lbl = QLabel()
        self.clock_lbl.setObjectName("headerClock")
        self.clock_lbl.hide()
        live_meta.addWidget(self.header_status)
        live_meta.addWidget(self.clock_lbl)
        right.addLayout(live_meta)
        hl.addLayout(right)
        global_layout.addWidget(self.global_header)

        # ── Central Stack ──
        self.stacked_widget = QStackedWidget()
        global_layout.addWidget(self.stacked_widget, stretch=1)
        
        # Stack 0: Start screen (Sequential / Manual). Cameras closed.
        self.mode_page = ModeSelectionPage()
        self.mode_page.sig_mode_selected.connect(self._on_mode_selected)
        self.mode_page.sig_redo_setup.connect(self._on_redo_camera_setup)
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

        # Stack 3: Camera setup once (assign, ROIs, hole connections)
        self.prep_page = PreInspectionSetupPage(self)
        self.prep_page.sig_continue.connect(self._on_prep_continue)
        self.prep_page.sig_back.connect(self._on_prep_back)
        self.prep_page.sig_assign.connect(self._on_assign_faces)
        self.prep_page.sig_rois.connect(self._on_edit_hole_rois)
        self.prep_page.sig_connections.connect(self._on_edit_hole_connections)
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
        cl.setSpacing(8)

        self.btn_start  = self._make_btn("▶  START",   "btnStart",  self._on_start, enabled=False)
        self.btn_stop   = self._make_btn("■  STOP",    "btnStop",   self._on_stop,   enabled=False)
        self.btn_pause  = self._make_btn("⏸  PAUSE",   "btnPause",  self._on_pause,  enabled=False)
        self.btn_resume = self._make_btn("⏵  RESUME",  "btnResume", self._on_resume, enabled=False)
        for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_resume):
            cl.addWidget(b)

        cl.addSpacing(12)
        self.btn_override = self._make_btn("✎  OVERRIDE", "btnOverride", self._on_override, enabled=False)
        cl.addWidget(self.btn_override)

        cl.addSpacing(8)
        self.btn_start_screen = self._make_btn("Start screen", "btnSetup", self._on_return_to_start, enabled=True)
        cl.addWidget(self.btn_start_screen)

        cl.addStretch()

        self.state_lbl = QLabel("Stopped")
        self.state_lbl.setStyleSheet("color: #5c6158; font-size: 11px; font-weight: 600; letter-spacing: 0.04em;")
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
        right_layout.setSpacing(8)

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
        
        # Initialize Layout (Hero = first enabled face)
        self._current_hero = None
        enabled = self.enabled_faces()
        self.set_hero_camera(enabled[0] if enabled else "A")

        # ── Footer: progress bar ──
        footer = QFrame()
        footer.setObjectName("footerBar")
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
        app_footer.setObjectName("appFooter")
        app_footer.setFixedHeight(36)
        footer_layout = QHBoxLayout(app_footer)
        footer_layout.setContentsMargins(24, 0, 24, 0)
        ver_lbl = QLabel(f"{SHELL_ORG} · {SHELL_PLANT} · {SHELL_DEPT}")
        ver_lbl.setObjectName("pageMeta")
        footer_layout.addWidget(ver_lbl)
        footer_layout.addStretch()
        global_layout.addWidget(app_footer)

        # ── Clock timer ──
        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick_clock)
        self._clock.start(1000)
        self._tick_clock()

        self.stacked_widget.currentChanged.connect(self._on_stack_page_changed)
        self.stacked_widget.setCurrentIndex(0)
        self._on_stack_page_changed(0)
        if SessionBusyOverlay is not None:
            self._busy_overlay = SessionBusyOverlay(central)
        self.showMaximized()

    def _on_stack_page_changed(self, index: int) -> None:
        if index == 4:
            kick = "Manual inspection" if self.selected_mode == "custom" else "Sequential cell"
        else:
            kick = PAGE_KICKERS.get(index, SHELL_APP)
        self.header_kicker.setText(str(kick).upper())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._busy_overlay is not None and self.centralWidget() is not None:
            self._busy_overlay.setGeometry(self.centralWidget().rect())

    def _port_map_ready(self) -> bool:
        from camera_indexer import check_port_map_exists

        cdir = self.config_dir or os.path.join(self.project_root, "config")
        return bool(check_port_map_exists(cdir))

    def _camera_setup_due(self) -> bool:
        if self._force_setup or not self._port_map_ready():
            return True
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        return not setup_is_complete(cdir)

    def _go_live_or_prep(self, manifold: str, prep_back: int) -> None:
        self.selected_manifold = manifold
        if self._camera_setup_due():
            self._prep_back_target = prep_back
            self.stacked_widget.setCurrentIndex(3)
        else:
            self._enter_live_dashboard(manifold)

    def _on_mode_selected(self, mode: str):
        self.selected_mode = mode
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        labels = manifold_labels(cdir)
        last = load_last_manifold(cdir, labels)
        if mode == "custom":
            self.custom_rule_id = None
            self.manual_setup_page.set_manifold_items(labels, last)
            self.manual_setup_page.set_initial_manifold(last)
            self.manual_setup_page.reload_from_disk()
            self.stacked_widget.setCurrentIndex(2)
            return
        if len(labels) > 1:
            self.manifold_page.set_manifold_items(labels, last)
            self.stacked_widget.setCurrentIndex(1)
            return
        self.custom_rule_id = None
        self._go_live_or_prep(labels[0] if labels else last, 0)

    def _on_manifold_selected(self, manifold: str):
        self.selected_manifold = manifold
        if self.selected_mode == "custom":
            self.custom_rule_id = None
            self.manual_setup_page.set_initial_manifold(manifold)
            self.manual_setup_page.reload_from_disk()
            self.stacked_widget.setCurrentIndex(2)
        else:
            self.custom_rule_id = None
            self._go_live_or_prep(manifold, 1)

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
            APP_STYLESHEET,
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
        self.stacked_widget.setCurrentIndex(0)

    def _on_manual_setup_continue(self):
        rid = self.manual_setup_page.get_rule_id()
        if not rid:
            return
        self.custom_rule_id = rid
        self.selected_manifold = self.manual_setup_page.get_manifold()
        self._go_live_or_prep(self.selected_manifold, 2)

    def _on_redo_camera_setup(self):
        self._force_setup = True
        QMessageBox.information(
            self,
            "Redo camera setup",
            "Choose Sequential or Manual, then the manifold.\n"
            "Assign camera faces, place hole ROIs, and hole connections open before the cameras start.",
        )

    def _on_prep_continue(self):
        m = (self.selected_manifold or "").strip()
        if not m:
            QMessageBox.warning(
                self,
                "Manifold",
                "Select a manifold before continuing to live inspection.",
            )
            return
        if not self._port_map_ready():
            QMessageBox.warning(
                self,
                "Assign camera faces",
                "Assign each USB camera to a face before opening the live view.",
            )
            return
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        mark_setup_complete(cdir, True)
        self._force_setup = False
        self._enter_live_dashboard(m)

    def _on_prep_back(self):
        self.stacked_widget.setCurrentIndex(self._prep_back_target)

    def bind_worker_ipc(self, comm_queues: Dict[str, Any], snapshot_queue) -> None:
        self._comm_queues = comm_queues or {}
        self._snapshot_queue = snapshot_queue

    def unbind_worker_ipc(self) -> None:
        self._comm_queues = {}
        self._snapshot_queue = None

    def _lock_live_bar(self, locked: bool) -> None:
        if locked:
            for b in (self.btn_start, self.btn_stop, self.btn_pause, self.btn_resume, self.btn_override, self.btn_start_screen):
                b.setEnabled(False)
            return
        self.btn_start_screen.setEnabled(True)
        if self._cameras_ready and not self.btn_stop.isEnabled():
            self.btn_start.setEnabled(True)

    def begin_camera_handshake(self, total: int) -> None:
        self._handshake_active = True
        self._cameras_ready = False
        self._failed_faces = []
        self._lock_live_bar(True)
        if self._busy_overlay is not None:
            self._busy_overlay.show_message(
                "Opening cameras",
                f"Face A (1 of {max(total, 1)}). Do not close this window.",
            )

    def report_camera_opening(self, face: str, index: int, total: int) -> None:
        if self._busy_overlay is not None:
            self._busy_overlay.show_message(
                "Opening cameras",
                f"Face {face} ({index} of {total}). Do not close this window.",
            )

    def report_camera_result(self, face: str, ok: bool) -> None:
        if ok:
            return
        self._failed_faces.append(str(face).upper())
        if self._busy_overlay is not None:
            self._busy_overlay.show_message(
                "Opening cameras",
                f"Face {face} did not open. Continuing with remaining cameras.",
            )

    def finish_camera_handshake(self) -> None:
        self._handshake_active = False
        self._cameras_ready = True
        if self._busy_overlay is not None:
            self._busy_overlay.clear()
        self._lock_live_bar(False)
        failed = ", ".join(self._failed_faces)
        if failed:
            QMessageBox.warning(
                self,
                "Some cameras did not open",
                f"These faces did not open: {failed}.\n"
                "The others stay live. START is available for the faces that opened.",
            )

    def _inspection_is_running(self) -> bool:
        return self.btn_stop.isEnabled() and not self.btn_resume.isEnabled()

    def _require_cameras_closed(self, title: str) -> bool:
        if self._handshake_active:
            QMessageBox.information(
                self,
                title,
                "Cameras are still opening. Wait, then use Start screen to close them.",
            )
            return False
        if self._workers_live():
            QMessageBox.warning(
                self,
                title,
                "Cameras are still open on the live view.\n"
                "Use Start screen to close them, then redo camera setup from the start screen.",
            )
            return False
        return True

    def _workers_live(self) -> bool:
        return bool(self._comm_queues)

    def _on_assign_faces(self):
        """Open the in-app face assignment wizard (same persist path as the CLI tool)."""
        if not HAS_PYQT6 or FaceAssignWizardDialog is None:
            QMessageBox.warning(
                self,
                "Assign faces",
                "Face assignment UI is unavailable.",
            )
            return
        if self._roi_session_open:
            QMessageBox.information(self, "Assign faces", "Close the ROI editor first.")
            return
        if not self._require_cameras_closed("Assign camera faces"):
            return
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        dlg = FaceAssignWizardDialog(cdir, APP_STYLESHEET, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.apply_resolved_cameras(self._all_camera_configs())
            QMessageBox.information(
                self,
                "Assignment saved",
                "Camera-face mapping saved. Sequential inspection will open those USB cameras.",
            )

    def apply_resolved_cameras(self, cameras: List[Dict[str, Any]]) -> None:
        """Apply indexer output (usb_index / enabled) to dashboard labels and layout."""
        self._cameras_list = list(cameras)
        enabled_set = set()
        for c in cameras:
            face = str(c.get("face", "")).upper()
            if not face:
                continue
            if c.get("usb_index") is not None:
                self._face_to_index[face] = int(c["usb_index"])
            if c.get("enabled", True):
                enabled_set.add(face)
        for face in ["A", "B", "C", "D", "E", "F"]:
            cw = self.camera_widgets.get(f"CAM_{face}")
            if cw:
                cw.set_usb_index(self._face_to_index.get(face), assigned=face in enabled_set)
        enabled = self.enabled_faces()
        if enabled:
            self.set_hero_camera(self._current_hero if self._current_hero in enabled else enabled[0])

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

    def _on_edit_hole_rois(self):
        if RoiEditorDialog is None:
            QMessageBox.warning(self, "Edit hole ROIs", "ROI editor is unavailable.")
            return
        if not self._require_cameras_closed("Edit hole ROIs"):
            return
        if not self._port_map_ready():
            QMessageBox.information(
                self,
                "Place hole ROIs",
                "Assign camera faces first so each face has a USB camera.",
            )
            return
        manifold = (self.selected_manifold or "").strip()
        if not manifold:
            QMessageBox.warning(self, "Edit hole ROIs", "Select a manifold first.")
            return
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        self._roi_session_open = True
        try:
            dlg = RoiEditorDialog(
                manifold,
                cdir,
                self._all_camera_configs(),
                None,
                None,
                APP_STYLESHEET,
                self,
                setup_mode=True,
            )
            dlg.exec()
        finally:
            self._roi_session_open = False

    def _on_edit_hole_connections(self):
        if RuleEditorDialog is None:
            QMessageBox.warning(self, "Hole connections", "Hole connections UI is unavailable.")
            return
        manifold = (self.selected_manifold or "").strip()
        if not manifold:
            QMessageBox.warning(self, "Hole connections", "Select a manifold first.")
            return
        if self.btn_stop.isEnabled():
            QMessageBox.warning(
                self,
                "Hole connections",
                "STOP inspection before editing hole connections.",
            )
            return
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        dlg = RuleEditorDialog(
            manifold,
            cdir,
            APP_STYLESHEET,
            inspection_running=self.btn_stop.isEnabled(),
            available_faces=set(self.enabled_faces()) or set("ABCDEF"),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted and getattr(dlg, "saved", False):
            if hasattr(self, "manual_setup_page"):
                self.manual_setup_page.reload_from_disk()
            self.sig_reload_rules.emit()

    def _enter_live_dashboard(self, manifold: str):
        self.selected_manifold = manifold
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        save_last_manifold(cdir, manifold)
        self.stacked_widget.setCurrentIndex(4)
        self.global_header.show()
        self.header_status.show()
        self.clock_lbl.show()
        self.btn_start.setEnabled(False)
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
                "color: #8a5a12; font-size: 18px; font-weight: bold;"
            )
            self.instruction_panel.face_hole_lbl.setText(
                "Check connectivity rules and camera availability, or use manual mode."
            )

    def enter_start_screen(self) -> None:
        """Show Sequential / Manual. Cameras must already be stopped."""
        self._handshake_active = False
        self._cameras_ready = False
        self._roi_session_open = False
        self.unbind_worker_ipc()
        if self._busy_overlay is not None:
            self._busy_overlay.clear()
        self.header_status.hide()
        self.clock_lbl.hide()
        self.stacked_widget.setCurrentIndex(0)
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(False)
        self.state_lbl.setText("Stopped")
        self.header_status.setText("Stopped")

    def _on_return_to_start(self):
        if self._handshake_active:
            QMessageBox.information(
                self,
                "Start screen",
                "Wait until cameras have finished opening.",
            )
            return
        if self._roi_session_open:
            QMessageBox.information(self, "Start screen", "Close the ROI editor first.")
            return
        if self._workers_live() or self.stacked_widget.currentIndex() == 4:
            box = QMessageBox(self)
            box.setWindowTitle("Close cameras")
            box.setText("Close all cameras and return to the start screen?")
            box.setInformativeText(
                "Assign faces, hole ROIs, and hole connections are on camera setup, before cameras open. "
                "USB cameras must be released first."
            )
            stay = box.addButton("Stay", QMessageBox.ButtonRole.RejectRole)
            close_btn = box.addButton("Close cameras", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(stay)
            box.exec()
            if box.clickedButton() != close_btn:
                return
        if self._busy_overlay is not None:
            self._busy_overlay.show_message(
                "Closing cameras",
                "Releasing USB devices, then returning to the start screen.",
            )
        self.sig_stop.emit()
        self.sig_return_to_setup.emit()

    def set_setup_event_loop(self, loop) -> None:
        """While waiting for manifold selection, closing the window quits this loop (see closeEvent)."""
        self._setup_event_loop = loop

    def set_inspect_event_loop(self, loop) -> None:
        self._inspect_event_loop = loop

    def closeEvent(self, event: QCloseEvent):
        from PyQt6.QtCore import QEventLoop, QTimer

        if self._handshake_active:
            box = QMessageBox(self)
            box.setWindowTitle("Cameras are still opening")
            box.setText("Cameras are still opening. Stop and quit?")
            box.setInformativeText("Closing now can leave USB cameras in a bad state.")
            stay = box.addButton("Stay", QMessageBox.ButtonRole.RejectRole)
            quit_btn = box.addButton("Stop and quit", QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(stay)
            box.exec()
            if box.clickedButton() != quit_btn:
                event.ignore()
                return
            self._handshake_active = False
            if self._busy_overlay is not None:
                self._busy_overlay.clear()

        self.shutdown_requested = True
        for loop in (getattr(self, "_setup_event_loop", None), getattr(self, "_inspect_event_loop", None)):
            if loop is not None and isinstance(loop, QEventLoop) and loop.isRunning():
                QTimer.singleShot(0, loop.quit)
        super().closeEvent(event)

    def enabled_faces(self) -> List[str]:
        """Faces that currently have an enabled camera (in-memory resolver state preferred)."""
        source = self._cameras_list or self._all_camera_configs()
        enabled: List[str] = []
        for c in source:
            face = str(c.get("face", "")).upper()
            if face and c.get("enabled", True) and face not in enabled:
                enabled.append(face)
        if not enabled:
            return ["A", "B", "C", "D", "E", "F"]
        order = "ABCDEF"
        enabled.sort(key=lambda f: order.index(f) if f in order else 99)
        return enabled

    def set_hero_camera(self, face_id: str):
        """
        Promotes the given face_id camera to the Hero slot.
        Demotes the previous hero to the thumbnail grid.
        Disabled / unassigned faces are hidden.
        """
        visible = self.enabled_faces()
        if face_id not in visible:
            face_id = visible[0] if visible else "A"

        target_cam = self.camera_widgets.get(f"CAM_{face_id}")
        if not target_cam:
            return

        if self._current_hero:
            prev_cam = self.camera_widgets.get(f"CAM_{self._current_hero}")
            if prev_cam:
                self.hero_layout.removeWidget(prev_cam)
                prev_cam.setParent(None)

        while self.hero_layout.count():
            item = self.hero_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        while self.thumb_layout.count():
            item = self.thumb_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        all_faces = ["A", "B", "C", "D", "E", "F"]
        thumb_faces = [f for f in visible if f != face_id]
        thumb_faces += [f for f in all_faces if f not in visible]

        thumb_idx = 0
        for f in thumb_faces:
            cw = self.camera_widgets.get(f"CAM_{f}")
            if not cw:
                continue
            row, col = divmod(thumb_idx, 3)
            self.thumb_layout.addWidget(cw, row, col)
            cw.setVisible(True)
            thumb_idx += 1

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
        if res == 'FAIL':
            self.header_status.setText("Fail detected")
            self.header_status.setStyleSheet(_status_pill_qss("fail"))
        elif res == 'PASS':
            self.header_status.setText("Running")
            self.header_status.setStyleSheet(_status_pill_qss("running"))

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
        if not self._cameras_ready or self._handshake_active:
            QMessageBox.information(
                self,
                "START",
                "Wait until cameras have finished opening.",
            )
            return
        self.sig_start.emit()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(True)
        self.state_lbl.setText("Running")
        self.header_status.setText("Running")
        self.header_status.setStyleSheet(_status_pill_qss("running"))

    def _on_stop(self):
        self.sig_stop.emit()
        self.btn_start.setEnabled(self._cameras_ready)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_override.setEnabled(False)
        self.state_lbl.setText("Stopped")
        self.header_status.setText("Stopped")
        self.header_status.setStyleSheet(_status_pill_qss("stopped"))

    def _on_pause(self):
        self.sig_pause.emit()
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)
        self.state_lbl.setText("Paused")
        self.header_status.setText("Paused")
        self.header_status.setStyleSheet(_status_pill_qss("paused"))

    def _on_resume(self):
        self.sig_resume.emit()
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.state_lbl.setText("Running")
        self.header_status.setText("Running")
        self.header_status.setStyleSheet(_status_pill_qss("running"))

    def _on_override(self):
        if not self._rule_ids:
            return
        dlg = OverrideDialog(self._rule_ids, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rule_id, result = dlg.get_selection()
            self.sig_override.emit(rule_id, result)

    def run_face_assign_wizard(self, required: bool = False) -> bool:
        """
        Show the face-assignment wizard. Returns True if the operator saved a mapping.
        When required=True, Cancel leaves no mapping (caller should exit).
        """
        if not HAS_PYQT6 or FaceAssignWizardDialog is None:
            if required and HAS_PYQT6:
                QMessageBox.warning(
                    self,
                    "Camera faces not assigned",
                    "Assign camera faces could not open. Check that PyQt6 is installed.",
                )
            return False
        cdir = self.config_dir or os.path.join(self.project_root, "config")
        try:
            dlg = FaceAssignWizardDialog(cdir, APP_STYLESHEET, self)
            saved = dlg.exec() == QDialog.DialogCode.Accepted
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Assign camera faces",
                "Could not open Assign camera faces.\n\n"
                f"{exc}",
            )
            return False
        if saved:
            self.apply_resolved_cameras(self._all_camera_configs())
        elif required:
            QMessageBox.warning(
                self,
                "Camera faces not assigned",
                "The inspection system needs a camera-face mapping before it can open USB cameras.\n"
                "Assign camera faces on the camera setup page after you choose the manifold.",
            )
        return saved


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

if HAS_PYQT6:
    def _quiet_qt_message(_mode, _context, message) -> None:
        text = str(message)
        if "Point size <= 0" in text:
            return
        sys.stderr.write(text + "\n")

    class InspectionApplication(QApplication):
        """Keeps one failed click or paint from closing the inspection window."""

        def __init__(self, argv):
            super().__init__(argv)
            self._handling_error = False

        def notify(self, receiver, event):
            try:
                return super().notify(receiver, event)
            except Exception as exc:
                if self._handling_error:
                    return False
                self._handling_error = True
                try:
                    QMessageBox.critical(
                        None,
                        "Something went wrong",
                        "That action did not finish. Cameras were left as they were.\n\n"
                        f"{type(exc).__name__}: {exc}",
                    )
                finally:
                    self._handling_error = False
                return False


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
        qInstallMessageHandler(_quiet_qt_message)
        app = QApplication.instance() or InspectionApplication(sys.argv)
        font = QFont("Segoe UI", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        app.setFont(font)
        app.setStyleSheet(APP_STYLESHEET)
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

"""Camera mapping and ROI calibration dialogs (PyQt6)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt

from config_loader import manifold_data_subdirectory


def scan_camera_indices() -> List[tuple]:
    """Return list of (index, opened_ok) for indices 0..9."""
    try:
        import cv2
    except ImportError:
        return []
    if sys.platform == "darwin":
        backend = cv2.CAP_AVFOUNDATION
    else:
        backend = cv2.CAP_ANY
    out = []
    for i in range(10):
        cap = cv2.VideoCapture(i, backend)
        ok_open = cap.isOpened()
        can_read = False
        if ok_open:
            can_read, _ = cap.read()
        cap.release()
        out.append((i, ok_open and can_read))
    return out


class CameraSetupDialog(QDialog):
    """Edit usb_index and enabled per face; writes cameras.json."""

    def __init__(self, cameras_file: str, stylesheet: str = "", parent=None):
        super().__init__(parent)
        self.cameras_file = cameras_file
        self.setWindowTitle("Camera USB mapping")
        self.resize(540, 440)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        self._data: Dict[str, Any] = {}
        self._spin_by_face: Dict[str, QSpinBox] = {}
        self._enabled_by_face: Dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("Map each manifold face to a USB camera index")
        title.setStyleSheet("color: #f0f6fc; font-size: 14px; font-weight: bold;")
        root.addWidget(title)

        hint = QLabel(
            "Default layout: Face A → USB 0 + hole_positions_cam0.json, … Face F → USB 5 + hole_positions_cam5.json. "
            "Change USB indices only if your wiring differs. Save writes cameras.json; restart the app so workers reload. "
            "Use Scan to see which indices open (brief freeze is normal)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 12px;")
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #30363d; border-radius: 6px; }")
        inner = QWidget()
        form = QFormLayout(inner)
        form.setSpacing(10)

        if os.path.isfile(cameras_file):
            try:
                with open(cameras_file, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

        face_order = "ABCDEF"
        cams = list(self._data.get("cameras", []))
        cams.sort(
            key=lambda c: face_order.index(c["face"])
            if c.get("face") in face_order
            else 99
        )
        for cam in cams:
            face = str(cam.get("face", "?"))
            row = QHBoxLayout()
            sp = QSpinBox()
            sp.setRange(0, 20)
            sp.setValue(int(cam.get("usb_index", 0)))
            en = QCheckBox("Enabled")
            en.setChecked(bool(cam.get("enabled", True)))
            self._spin_by_face[face] = sp
            self._enabled_by_face[face] = en
            row.addWidget(sp)
            row.addWidget(en)
            row.addStretch()
            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(f"Face {face}", wrap)

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        scan_btn = QPushButton("Scan indices 0–9")
        scan_btn.setObjectName("btnSetup")
        scan_btn.clicked.connect(self._on_scan)
        root.addWidget(scan_btn)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("btnStart")
        cancel_btn = QPushButton("Close")
        cancel_btn.setObjectName("btnSetup")
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _on_scan(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            results = scan_camera_indices()
        finally:
            QApplication.restoreOverrideCursor()
        lines = [f"  USB {idx}: {'OK' if ok else '—'}" for idx, ok in results]
        QMessageBox.information(
            self,
            "Camera scan",
            "Results (quick open + read test):\n\n" + "\n".join(lines),
        )

    def _save(self):
        for cam in self._data.get("cameras", []):
            face = str(cam.get("face", ""))
            if face in self._spin_by_face:
                cam["usb_index"] = self._spin_by_face[face].value()
            if face in self._enabled_by_face:
                cam["enabled"] = self._enabled_by_face[face].isChecked()
        try:
            with open(self.cameras_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        QMessageBox.information(
            self,
            "Saved",
            f"Wrote:\n{self.cameras_file}\n\nRestart the application for changes to take effect.",
        )
        self.accept()


class CalibrateRoiDialog(QDialog):
    """Pick face and launch calibrate.py for the current manifold."""

    def __init__(
        self,
        cameras: List[Dict[str, Any]],
        manifold: str,
        config_dir: str,
        project_root: str,
        stylesheet: str = "",
        data_subdir: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._cameras = cameras
        self._manifold = manifold or "DALIA"
        self._data_subdir = data_subdir or manifold_data_subdirectory(self._manifold)
        self._config_dir = config_dir
        self._project_root = project_root

        self.setWindowTitle("Calibrate ROIs")
        if stylesheet:
            self.setStyleSheet(stylesheet)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Face to calibrate (opens OpenCV window; close it when done):"))

        self.combo = QComboBox()
        face_order = "ABCDEF"
        ordered = sorted(
            cameras,
            key=lambda c: face_order.index(c["face"])
            if c.get("face") in face_order
            else 99,
        )
        for cam in ordered:
            face = cam.get("face")
            if face is None:
                continue
            usb = cam.get("usb_index")
            en = cam.get("enabled", True)
            suffix = "" if en else " — disabled"
            self.combo.addItem(f"Face {face}  (USB {usb}){suffix}", userData=face)
        layout.addWidget(self.combo)

        roi_hint = QLabel(
            f"Manifold: {self._manifold} — ROI files: config/{self._data_subdir}/hole_positions_camN.json "
            f"(N = USB index). Values on disk stay the same until you save in the calibration tool."
        )
        roi_hint.setWordWrap(True)
        layout.addWidget(roi_hint)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._launch)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _launch(self):
        face = self.combo.currentData()
        if not face:
            QMessageBox.warning(self, "Calibrate", "No camera selected.")
            return
        cam = next((c for c in self._cameras if c.get("face") == face), None)
        if not cam:
            QMessageBox.warning(self, "Calibrate", "Camera config not found.")
            return
        usb = int(cam.get("usb_index", 0))
        base = os.path.basename(cam.get("config", "hole_positions_cam0.json"))
        roi_path = os.path.normpath(os.path.join(self._config_dir, self._data_subdir, base))
        cal_script = os.path.join(self._project_root, "calibrate.py")
        if not os.path.isfile(cal_script):
            QMessageBox.critical(self, "Calibrate", f"Missing:\n{cal_script}")
            return
        os.makedirs(os.path.dirname(roi_path), exist_ok=True)
        try:
            subprocess.Popen(
                [sys.executable, cal_script, "--cam", str(usb), "--config", roi_path],
                cwd=self._project_root,
            )
        except OSError as e:
            QMessageBox.critical(self, "Calibrate", str(e))
            return
        QMessageBox.information(
            self,
            "Calibrate",
            "Calibration tool started in a separate window.\n"
            "Stop the main inspection first if the camera is already in use.",
        )
        self.accept()

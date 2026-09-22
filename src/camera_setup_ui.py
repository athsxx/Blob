"""Camera mapping and ROI calibration dialogs (PyQt6)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from config_loader import face_roi_basename, manifold_data_subdirectory


class _FaceAssignScanThread(QThread):
    """Sequential snapshot scan for the in-app face assignment wizard."""

    progress = pyqtSignal(str)
    scan_done = pyqtSignal(list)
    scan_failed = pyqtSignal(str)

    def __init__(self, max_index: int = 9, parent=None):
        super().__init__(parent)
        self._max_index = max_index

    def run(self) -> None:
        try:
            from camera_assign import attach_port_paths, scan_cameras

            found = scan_cameras(
                max_index=self._max_index,
                progress=lambda msg: self.progress.emit(msg),
            )
            attach_port_paths(found)
            self.scan_done.emit(found)
        except Exception as exc:
            self.scan_failed.emit(str(exc))


def _bgr_to_pixmap(frame, max_width: int = 280) -> QPixmap:
    """Convert an OpenCV BGR ndarray to a scaled QPixmap (copied, buffer-safe)."""
    h, w = frame.shape[:2]
    rgb = frame[..., ::-1].copy()
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    pix = QPixmap.fromImage(qimg)
    if w > max_width:
        pix = pix.scaled(
            max_width,
            max(1, int(max_width * h / max(w, 1))),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pix


class FaceAssignWizardDialog(QDialog):
    """
    In-app replacement for tools/assign_camera_faces.py.

    Scans USB cameras one at a time, shows a snapshot per index, lets the
    operator pick face A–F, then writes camera_port_map.json + cameras.json
    through camera_assign.persist_assignments().
    """

    def __init__(self, config_dir: str, stylesheet: str = "", parent=None):
        super().__init__(parent)
        self.config_dir = config_dir
        self._scan_thread: Optional[_FaceAssignScanThread] = None
        self._cameras: List[Dict[str, Any]] = []
        self._face_combo: Dict[int, QComboBox] = {}
        self.summary: Optional[Dict[str, Any]] = None

        self.setWindowTitle("Assign camera faces")
        self.resize(980, 640)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        title = QLabel("Assign each USB camera to a manifold face (A–F)")
        title.setStyleSheet("color: #f0f6fc; font-size: 14px; font-weight: bold;")
        root.addWidget(title)

        hint = QLabel(
            "Look at each snapshot and choose the manifold face that camera is watching. "
            "Skip unused cameras. Unassigned faces are disabled so they do not spawn "
            "workers. ROI files stay bound to the face letter (Face A → hole_positions_cam0.json), "
            "not the USB index. After saving, restart inspection so workers reload."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e; font-size: 12px;")
        root.addWidget(hint)

        self._status = QLabel("Click Scan cameras to capture snapshots (one device at a time).")
        self._status.setStyleSheet("color: #79c0ff; font-size: 12px;")
        root.addWidget(self._status)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { border: 1px solid #30363d; border-radius: 6px; }")
        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(12)
        self._scroll.setWidget(self._grid_host)
        root.addWidget(self._scroll, stretch=1)

        self._disable_unassigned = QCheckBox("Disable faces with no camera (recommended)")
        self._disable_unassigned.setChecked(True)
        root.addWidget(self._disable_unassigned)

        btn_row = QHBoxLayout()
        self._scan_btn = QPushButton("Scan cameras")
        self._scan_btn.setObjectName("btnSetup")
        self._scan_btn.clicked.connect(self._start_scan)
        save_btn = QPushButton("Save assignment")
        save_btn.setObjectName("btnStart")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("Cancel")
        close_btn.setObjectName("btnSetup")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._scan_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

        self._start_scan()

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._face_combo.clear()

    def _start_scan(self) -> None:
        if self._scan_thread is not None and self._scan_thread.isRunning():
            return
        self._scan_btn.setEnabled(False)
        self._status.setText("Scanning USB cameras… keep other camera apps closed.")
        self._clear_grid()
        self._scan_thread = _FaceAssignScanThread(parent=self)
        self._scan_thread.progress.connect(self._status.setText)
        self._scan_thread.scan_done.connect(self._on_scan_done)
        self._scan_thread.scan_failed.connect(self._on_scan_failed)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_scan_failed(self, message: str) -> None:
        self._scan_btn.setEnabled(True)
        self._scan_thread = None
        self._status.setText("Scan failed.")
        QMessageBox.critical(self, "Camera scan failed", message)

    def _on_scan_done(self, cameras: List[Dict[str, Any]]) -> None:
        self._scan_btn.setEnabled(True)
        self._scan_thread = None
        self._cameras = cameras
        if not cameras:
            self._status.setText("No cameras found. Check USB power and cables.")
            return
        self._status.setText(f"Found {len(cameras)} camera(s). Assign a unique face to each.")
        from camera_assign import VALID_FACES

        for i, cam in enumerate(cameras):
            tile = QWidget()
            tl = QVBoxLayout(tile)
            tl.setContentsMargins(8, 8, 8, 8)
            tl.setSpacing(6)
            img = QLabel()
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setStyleSheet("background-color: #161b22; border-radius: 6px;")
            img.setPixmap(_bgr_to_pixmap(cam["frame"]))
            tl.addWidget(img)
            path = str(cam.get("port_path") or "")
            short = path if len(path) < 52 else path[:24] + "…" + path[-24:]
            meta = QLabel(f"USB {cam['index']}  ·  {cam['width']}×{cam['height']}\n{short}")
            meta.setWordWrap(True)
            meta.setStyleSheet("color: #8b949e; font-size: 11px;")
            tl.addWidget(meta)
            combo = QComboBox()
            combo.addItem("Skip (not used)", userData="")
            for face in VALID_FACES:
                combo.addItem(f"Face {face}", userData=face)
            # Pre-select Face letter in scan order when possible (A, B, C…).
            if i < len(VALID_FACES):
                combo.setCurrentIndex(i + 1)
            self._face_combo[int(cam["index"])] = combo
            tl.addWidget(combo)
            row, col = divmod(i, 3)
            self._grid.addWidget(tile, row, col)

    def _save(self) -> None:
        from camera_assign import persist_assignments

        chosen: Dict[str, Dict[str, Any]] = {}
        assignments: List[Dict[str, Any]] = []
        for cam in self._cameras:
            combo = self._face_combo.get(int(cam["index"]))
            if combo is None:
                continue
            face = combo.currentData()
            if not face:
                continue
            if face in chosen:
                QMessageBox.warning(
                    self,
                    "Duplicate face",
                    f"Face {face} is assigned to more than one camera. Each face must be unique.",
                )
                return
            chosen[face] = cam
            assignments.append({
                "face": face,
                "usb_index": int(cam["index"]),
                "port_path": cam.get("port_path"),
                "device_description": cam.get("device_description"),
            })
        if not assignments:
            QMessageBox.warning(self, "Assign faces", "Assign at least one camera to a face.")
            return
        try:
            self.summary = persist_assignments(
                self.config_dir,
                assignments,
                disable_unassigned=self._disable_unassigned.isChecked(),
            )
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        disabled = ", ".join(self.summary.get("disabled") or []) or "none"
        QMessageBox.information(
            self,
            "Assignment saved",
            f"Wrote {self.summary['port_map_path']}\n"
            f"Assigned faces: {', '.join(self.summary['assigned'])}\n"
            f"Disabled faces: {disabled}\n\n"
            "Restart the application (or continue setup) so workers use this mapping.",
        )
        self.accept()


class CalibrateRoiDialog(QDialog):
    """Lab fallback: pick face and launch calibrate.py after the app has fully quit."""

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
        self._config_dir = config_dir
        self._project_root = project_root
        self._data_subdir = data_subdir or manifold_data_subdirectory(
            self._manifold, self._config_dir
        )

        self.setWindowTitle("Calibrate ROIs")
        if stylesheet:
            self.setStyleSheet(stylesheet)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Lab fallback only — quit the inspection app first so USB is free:"))

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
            en = cam.get("enabled", True)
            suffix = "" if en else " — disabled"
            roi_name = face_roi_basename(str(face))
            self.combo.addItem(f"Face {face}  ({roi_name}){suffix}", userData=face)
        layout.addWidget(self.combo)

        roi_hint = QLabel(
            f"Manifold: {self._manifold} — ROI files: config/{self._data_subdir}/"
            f"hole_positions_camN.json (N is face ordinal: Face A = cam0 … Face F = cam5, not USB index). "
            "Prefer Place hole ROIs on the camera setup page (cameras closed)."
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
        base = face_roi_basename(str(face))
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
            "Lab calibration tool started in a separate window.\n"
            "This opens a second camera capture — only use it after fully quitting the inspection app.",
        )
        self.accept()


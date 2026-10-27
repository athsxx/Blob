"""Add-manifold wizard: name, config folder, copy rules template, per-face ROI calibration."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from functools import partial
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QComboBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from config_loader import (
    load_manifold_registry_entries,
    load_all_cameras_from_file,
    save_manifold_registry_entries,
    list_config_subdirs_with_rules,
    slug_manifold_folder_id,
    validate_manifold_folder_id,
    face_roi_basename,
)
from connectivity_rules_io import inject_inspection_template, write_rules_from_workbook

EMPTY_ROIS: Dict[str, Any] = {"circles": []}
BLANK_TEMPLATE = "__blank__"


class _ManifoldDiskWorker(QThread):
    """Create manifold folder, ROI stubs, and registry entry off the GUI thread."""

    succeeded = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        config_dir: str,
        display: str,
        folder_id: str,
        template: str,
        face_basenames: Dict[str, str],
        parent=None,
    ):
        super().__init__(parent)
        self._config_dir = config_dir
        self._display = display
        self._folder_id = folder_id
        self._template = template
        self._face_basenames = dict(face_basenames)

    def run(self) -> None:
        try:
            dest_dir = os.path.join(self._config_dir, self._folder_id)
            os.makedirs(dest_dir, exist_ok=True)
            if self._template == BLANK_TEMPLATE:
                inject_inspection_template(dest_dir, self._config_dir)
            else:
                src_dir = os.path.join(self._config_dir, self._template)
                src_sheet = os.path.join(src_dir, "manifold_inspection.xlsx")
                if not os.path.isfile(src_sheet):
                    src_sheet = os.path.join(src_dir, "dalia_manifold_inspection.xlsx")
                if os.path.isfile(src_sheet):
                    dest_sheet = os.path.join(dest_dir, "manifold_inspection.xlsx")
                    shutil.copy2(src_sheet, dest_sheet)
                    write_rules_from_workbook(
                        dest_sheet,
                        os.path.join(dest_dir, "connectivity_rules.json"),
                    )
                else:
                    src_rules = os.path.join(src_dir, "connectivity_rules.json")
                    shutil.copy2(src_rules, os.path.join(dest_dir, "connectivity_rules.json"))
            names = {face_roi_basename(face) for face in "ABCDEF"}
            names.update(self._face_basenames.values())
            for base in sorted(names):
                p = os.path.join(dest_dir, base)
                if not os.path.isfile(p):
                    with open(p, "w", encoding="utf-8") as handle:
                        json.dump(EMPTY_ROIS, handle, indent=2)
                        handle.write("\n")
            entries = load_manifold_registry_entries(self._config_dir)
            entries.append({"label": self._display, "folder": self._folder_id})
            save_manifold_registry_entries(self._config_dir, entries)
            self.succeeded.emit()
        except (OSError, ValueError) as e:
            self.failed.emit(str(e))


class AddManifoldDialog(QDialog):
    """
    Create config/<folder>/. A blank manifold receives the standard inspection
    sheet, and connectivity_rules.json is built from that sheet.
    """

    def __init__(
        self,
        config_dir: str,
        project_root: str,
        cameras_file: str,
        stylesheet: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._config_dir = os.path.abspath(config_dir)
        self._project_root = os.path.abspath(project_root)
        self._cameras_file = os.path.abspath(cameras_file)
        self.created_label: Optional[str] = None
        self._created_folder: Optional[str] = None
        self._disk_worker: Optional[_ManifoldDiskWorker] = None

        self.setWindowTitle("Add manifold")
        self.resize(560, 520)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        self._cameras: List[Dict[str, Any]] = load_all_cameras_from_file(self._cameras_file)
        self._face_rows: Dict[str, Dict[str, Any]] = {}
        for face in "ABCDEF":
            cam = next((c for c in self._cameras if str(c.get("face")) == face), None)
            self._face_rows[face] = {"cam": cam}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        root.addWidget(QLabel(
            "Create a new manifold from the blank inspection sheet, or copy an existing manifold's rules."
        ))

        form = QFormLayout()
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("e.g. Plant 8 — Line B")
        self.edit_folder = QLineEdit()
        self.edit_folder.setPlaceholderText("Auto from name (e.g. Plant_8_Line_B)")
        self._folder_user_edited = False
        self.edit_name.textChanged.connect(self._on_name_changed)
        self.edit_folder.textEdited.connect(lambda: setattr(self, "_folder_user_edited", True))
        form.addRow("Display name", self.edit_name)
        form.addRow("Config folder id", self.edit_folder)
        root.addLayout(form)

        self.combo_template = QComboBox()
        self._reload_templates_combo()
        root.addWidget(QLabel("Start from:"))
        root.addWidget(self.combo_template)

        self.btn_create = QPushButton("Create manifold on disk")
        self.btn_create.setObjectName("pagePrimary")
        self.btn_create.clicked.connect(self._on_create)
        root.addWidget(self.btn_create)

        self.status_lbl = QLabel(
            "The blank sheet is copied in, then the rules file is built from that sheet. "
            "Fill HOLE OPEN and the same columns become the rules."
        )
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setObjectName("pageHint")
        root.addWidget(self.status_lbl)

        faces_box = QGroupBox("ROI files per face (USB from cameras.json → calibrate.py --cam)")
        faces_layout = QVBoxLayout(faces_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setColumnStretch(3, 1)
        grid.addWidget(QLabel("Face"), 0, 0)
        grid.addWidget(QLabel("USB"), 0, 1)
        grid.addWidget(QLabel("ROI file"), 0, 2)
        grid.addWidget(QLabel(""), 0, 3)

        row = 1
        for face in "ABCDEF":
            info = self._face_rows[face]
            cam = info["cam"]
            usb_lbl = QLabel("—")
            file_lbl = QLabel("—")
            cal_btn = QPushButton("Calibrate…")
            cal_btn.setObjectName("btnSetup")
            cal_btn.setEnabled(False)
            if cam is not None:
                usb = cam.get("usb_index")
                base = os.path.basename(str(cam.get("config", f"hole_positions_cam{usb}.json")))
                usb_lbl.setText(str(usb))
                file_lbl.setText(base)
                cal_btn.setProperty("face", face)
                cal_btn.clicked.connect(lambda checked, f=face: self._on_calibrate_face(f))
            else:
                usb_lbl.setText("—")
                file_lbl.setText("(no camera in cameras.json)")
                cal_btn.setEnabled(False)
            info["btn"] = cal_btn
            grid.addWidget(QLabel(f"Face {face}"), row, 0)
            grid.addWidget(usb_lbl, row, 1)
            grid.addWidget(file_lbl, row, 2)
            grid.addWidget(cal_btn, row, 3)
            row += 1

        scroll.setWidget(inner)
        faces_layout.addWidget(scroll)
        root.addWidget(faces_box, stretch=1)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("btnSetup")
        btn_close.clicked.connect(self.reject)
        root.addWidget(btn_close)

    def _reload_templates_combo(self):
        self.combo_template.clear()
        self.combo_template.addItem("Blank standard sheet", userData=BLANK_TEMPLATE)
        for name in list_config_subdirs_with_rules(self._config_dir):
            self.combo_template.addItem(f"Copy {name}", userData=name)

    def _on_name_changed(self, text: str):
        if not self._folder_user_edited:
            self.edit_folder.blockSignals(True)
            self.edit_folder.setText(slug_manifold_folder_id(text))
            self.edit_folder.blockSignals(False)

    def _on_create(self):
        display = self.edit_name.text().strip()
        folder_id = self.edit_folder.text().strip()
        if not display:
            QMessageBox.warning(self, "Add manifold", "Enter a display name.")
            return
        ok, err = validate_manifold_folder_id(folder_id)
        if not ok:
            QMessageBox.warning(self, "Add manifold", err)
            return

        template = self.combo_template.currentData()
        if template != BLANK_TEMPLATE:
            src_rules = os.path.join(self._config_dir, str(template), "connectivity_rules.json")
            if not os.path.isfile(src_rules):
                QMessageBox.critical(self, "Add manifold", f"Missing template rules:\n{src_rules}")
                return
        entries = load_manifold_registry_entries(self._config_dir)
        if any(str(e.get("label", "")).strip() == display for e in entries):
            QMessageBox.warning(self, "Add manifold", "A manifold with this display name already exists.")
            return
        if any(str(e.get("folder", "")).strip() == folder_id for e in entries):
            QMessageBox.warning(self, "Add manifold", "This folder id is already used by another manifold entry.")
            return

        dest_dir = os.path.join(self._config_dir, folder_id)
        if os.path.exists(dest_dir):
            QMessageBox.warning(self, "Add manifold", f"Folder already exists:\n{dest_dir}")
            return

        if self._disk_worker is not None and self._disk_worker.isRunning():
            return

        face_basenames: Dict[str, str] = {}
        for face in "ABCDEF":
            cam = self._face_rows[face]["cam"]
            if not cam:
                continue
            base = os.path.basename(
                str(cam.get("config", f"hole_positions_cam{cam.get('usb_index', 0)}.json"))
            )
            face_basenames[face] = base

        self.btn_create.setEnabled(False)
        self.status_lbl.setText("Creating folder and files…")

        self._disk_worker = _ManifoldDiskWorker(
            self._config_dir,
            display,
            folder_id,
            template,
            face_basenames,
            self,
        )
        self._disk_worker.succeeded.connect(
            partial(self._on_create_disk_done, display, folder_id)
        )
        self._disk_worker.failed.connect(self._on_create_disk_failed)
        self._disk_worker.finished.connect(self._disk_worker.deleteLater)
        self._disk_worker.start()

    def _on_create_disk_done(self, display: str, folder_id: str) -> None:
        self._created_folder = folder_id
        self.created_label = display
        for face in "ABCDEF":
            btn = self._face_rows[face].get("btn")
            if btn and self._face_rows[face]["cam"] is not None:
                btn.setEnabled(True)
        self.btn_create.setEnabled(False)
        self.status_lbl.setText(
            f"Created config/{folder_id}/. Registry updated. Calibrate each face; press 's' in the tool to save ROIs."
        )
        self._disk_worker = None
        QMessageBox.information(
            self,
            "Manifold created",
            f"{display}\n\nFolder: config/{folder_id}/\n\nSelect it in the manifold list after closing this dialog.",
        )

    def _on_create_disk_failed(self, message: str) -> None:
        self.btn_create.setEnabled(True)
        self.status_lbl.setText(
            "After creation, use Calibrate per face (USB indices match cameras.json)."
        )
        self._disk_worker = None
        QMessageBox.critical(self, "Add manifold", message)

    def _on_calibrate_face(self, face: str):
        if not self._created_folder:
            QMessageBox.warning(self, "Calibrate", "Create the manifold first.")
            return
        info = self._face_rows.get(face) or {}
        cam = info.get("cam")
        if not cam:
            return
        usb = int(cam.get("usb_index", 0))
        base = os.path.basename(str(cam.get("config", f"hole_positions_cam{usb}.json")))
        roi_path = os.path.normpath(os.path.join(self._config_dir, self._created_folder, base))
        cal_script = os.path.join(self._project_root, "calibrate.py")
        if not os.path.isfile(cal_script):
            QMessageBox.critical(self, "Calibrate", f"Missing:\n{cal_script}")
            return
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
            f"Started calibration for Face {face} (USB {usb}).\n"
            f"File: {roi_path}\n\nPress 's' in the OpenCV window to save. Quit other apps using this camera if open fails.",
        )

"""Add-manifold wizard: name, config folder, template or spreadsheet import, and in-app ROI/Rule setup."""
from __future__ import annotations

import json
import os
import shutil
from functools import partial
from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
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

from capture_profile import load_capture_profile
from config_loader import (
    load_manifold_registry_entries,
    load_all_cameras_from_file,
    save_manifold_registry_entries,
    list_config_subdirs_with_rules,
    slug_manifold_folder_id,
    validate_manifold_folder_id,
    face_roi_basename,
    mark_setup_complete,
)
from connectivity_rules_io import (
    INSPECTION_WORKBOOK_NAME,
    ensure_standard_template,
    inject_inspection_template,
    write_connections_workbook,
    write_rules_from_workbook,
)

BLANK_TEMPLATE = "__blank__"
IMPORT_SPREADSHEET = "__xlsx__"


class _ManifoldDiskWorker(QThread):
    """Create manifold folder, ROI stubs, and registry entry off the GUI thread."""

    succeeded = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(
        self,
        config_dir: str,
        display: str,
        folder_id: str,
        template: str,
        xlsx_path: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._config_dir = config_dir
        self._display = display
        self._folder_id = folder_id
        self._template = template
        self._xlsx_path = xlsx_path

    def run(self) -> None:
        dest_dir = os.path.join(self._config_dir, self._folder_id)
        created_dir = False
        try:
            os.makedirs(dest_dir, exist_ok=False)
            created_dir = True
            rule_count = 0

            if self._template == BLANK_TEMPLATE:
                rule_count = inject_inspection_template(dest_dir, self._config_dir)
            elif self._template == IMPORT_SPREADSHEET and self._xlsx_path:
                dest_sheet = os.path.join(dest_dir, INSPECTION_WORKBOOK_NAME)
                shutil.copy2(self._xlsx_path, dest_sheet)
                rule_count = write_rules_from_workbook(
                    dest_sheet,
                    os.path.join(dest_dir, "connectivity_rules.json"),
                )
            else:
                src_dir = os.path.join(self._config_dir, self._template)
                src_rules = os.path.join(src_dir, "connectivity_rules.json")
                dest_rules = os.path.join(dest_dir, "connectivity_rules.json")
                if os.path.isfile(src_rules):
                    shutil.copy2(src_rules, dest_rules)
                    with open(dest_rules, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    rules_list = data.get("rules") or []
                    rule_count = len(rules_list)
                    src_sheet = os.path.join(src_dir, INSPECTION_WORKBOOK_NAME)
                    if not os.path.isfile(src_sheet):
                        src_sheet = os.path.join(src_dir, "dalia_manifold_inspection.xlsx")
                    dest_sheet = os.path.join(dest_dir, INSPECTION_WORKBOOK_NAME)
                    if os.path.isfile(src_sheet):
                        shutil.copy2(src_sheet, dest_sheet)
                    else:
                        write_connections_workbook(dest_sheet, rules_list)
                else:
                    src_sheet = os.path.join(src_dir, INSPECTION_WORKBOOK_NAME)
                    if not os.path.isfile(src_sheet):
                        src_sheet = os.path.join(src_dir, "dalia_manifold_inspection.xlsx")
                    dest_sheet = os.path.join(dest_dir, INSPECTION_WORKBOOK_NAME)
                    shutil.copy2(src_sheet, dest_sheet)
                    rule_count = write_rules_from_workbook(dest_sheet, dest_rules)

            profile = load_capture_profile(self._config_dir)
            calib_w = int(profile.get("width") or 1280)
            calib_h = int(profile.get("height") or 800)
            empty_rois = {
                "calib_width": calib_w,
                "calib_height": calib_h,
                "circles": [],
            }
            for face in "ABCDEF":
                base = face_roi_basename(face)
                p = os.path.join(dest_dir, base)
                if not os.path.isfile(p):
                    with open(p, "w", encoding="utf-8") as handle:
                        json.dump(empty_rois, handle, indent=2)
                        handle.write("\n")

            entries = load_manifold_registry_entries(self._config_dir)
            entries.append({"label": self._display, "folder": self._folder_id})
            save_manifold_registry_entries(self._config_dir, entries)
            mark_setup_complete(self._config_dir, False, self._display)
            self.succeeded.emit(rule_count)
        except Exception as e:
            if created_dir and os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir, ignore_errors=True)
            self.failed.emit(str(e))


class AddManifoldDialog(QDialog):
    """
    Create config/<folder>/. Supports starting from:
    - Blank standard inspection sheet (with exportable template)
    - Importing a filled Excel (.xlsx / .csv) inspection sheet directly
    - Copying an existing manifold's rules
    And opens the in-app Hole Connections and ROI Editor directly.
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
        self._stylesheet = stylesheet
        self.created_label: Optional[str] = None
        self._created_folder: Optional[str] = None
        self._disk_worker: Optional[_ManifoldDiskWorker] = None
        self._import_xlsx_path: str = ""

        self.setWindowTitle("Add manifold")
        self.resize(620, 560)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        self._cameras: List[Dict[str, Any]] = load_all_cameras_from_file(self._cameras_file)
        self._face_rows: Dict[str, Dict[str, Any]] = {}
        for face in "ABCDEF":
            cam = next((c for c in self._cameras if str(c.get("face")).upper() == face), None)
            self._face_rows[face] = {"cam": cam}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top_row = QHBoxLayout()
        top_lbl = QLabel(
            "Create a new manifold folder with its own Excel check sheet, rules, and 6 face ROI files."
        )
        top_lbl.setWordWrap(True)
        top_row.addWidget(top_lbl, stretch=1)
        self.btn_export_template = QPushButton("Export blank Excel template…")
        self.btn_export_template.setObjectName("btnSetup")
        self.btn_export_template.setToolTip(
            "Save a copy of the standard HOLE OPEN Excel template with dropdowns and HOW TO FILL instructions."
        )
        self.btn_export_template.clicked.connect(self._on_export_template)
        top_row.addWidget(self.btn_export_template)
        root.addLayout(top_row)

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
        self.combo_template.currentIndexChanged.connect(self._on_template_source_changed)
        root.addWidget(QLabel("Start rules from:"))
        root.addWidget(self.combo_template)

        self._xlsx_row_widget = QWidget()
        xlsx_row = QHBoxLayout(self._xlsx_row_widget)
        xlsx_row.setContentsMargins(0, 0, 0, 0)
        xlsx_row.setSpacing(8)
        self.edit_xlsx_path = QLineEdit()
        self.edit_xlsx_path.setReadOnly(True)
        self.edit_xlsx_path.setPlaceholderText("Choose a filled manifold_inspection.xlsx sheet…")
        self.btn_browse_xlsx = QPushButton("Browse sheet…")
        self.btn_browse_xlsx.setObjectName("btnSetup")
        self.btn_browse_xlsx.clicked.connect(self._on_browse_xlsx)
        xlsx_row.addWidget(self.edit_xlsx_path, stretch=1)
        xlsx_row.addWidget(self.btn_browse_xlsx)
        self._xlsx_row_widget.hide()
        root.addWidget(self._xlsx_row_widget)

        self.btn_create = QPushButton("Create manifold on disk")
        self.btn_create.setObjectName("pagePrimary")
        self.btn_create.clicked.connect(self._on_create)
        root.addWidget(self.btn_create)

        self.status_lbl = QLabel(
            "Supporting files created in config/<folder_id>/: manifold_inspection.xlsx, "
            "connectivity_rules.json, and hole_positions_cam0..5.json (Faces A–F)."
        )
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setObjectName("pageHint")
        root.addWidget(self.status_lbl)

        faces_box = QGroupBox("Supporting files & setup actions (Face A = cam0 … Face F = cam5)")
        faces_layout = QVBoxLayout(faces_box)
        action_row = QHBoxLayout()
        self.btn_open_rules = QPushButton("1. Edit / Load Hole Connections…")
        self.btn_open_rules.setObjectName("btnSetup")
        self.btn_open_rules.setEnabled(False)
        self.btn_open_rules.clicked.connect(self._on_open_rule_editor)
        self.btn_open_rois = QPushButton("2. Place Hole ROIs (Faces A–F)…")
        self.btn_open_rois.setObjectName("btnSetup")
        self.btn_open_rois.setEnabled(False)
        self.btn_open_rois.clicked.connect(self._on_open_roi_editor)
        action_row.addWidget(self.btn_open_rules)
        action_row.addWidget(self.btn_open_rois)
        faces_layout.addLayout(action_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setColumnStretch(2, 1)
        grid.addWidget(QLabel("Face"), 0, 0)
        grid.addWidget(QLabel("USB"), 0, 1)
        grid.addWidget(QLabel("Canonical ROI File"), 0, 2)

        for row, face in enumerate("ABCDEF", start=1):
            info = self._face_rows[face]
            cam = info["cam"]
            usb_text = str(cam.get("usb_index")) if cam and cam.get("usb_index") is not None else "—"
            base = face_roi_basename(face)
            grid.addWidget(QLabel(f"Face {face}"), row, 0)
            grid.addWidget(QLabel(usb_text), row, 1)
            grid.addWidget(QLabel(base), row, 2)

        scroll.setWidget(inner)
        faces_layout.addWidget(scroll)
        root.addWidget(faces_box, stretch=1)

        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("btnSetup")
        self.btn_close.clicked.connect(self.reject)
        root.addWidget(self.btn_close)

    def _reload_templates_combo(self):
        self.combo_template.clear()
        self.combo_template.addItem("Blank standard sheet (HOLE OPEN template)", userData=BLANK_TEMPLATE)
        self.combo_template.addItem("Import filled Excel sheet (.xlsx / .csv)…", userData=IMPORT_SPREADSHEET)
        for name in list_config_subdirs_with_rules(self._config_dir):
            self.combo_template.addItem(f"Copy existing manifold ({name})", userData=name)

    def _on_template_source_changed(self) -> None:
        is_xlsx = self.combo_template.currentData() == IMPORT_SPREADSHEET
        self._xlsx_row_widget.setVisible(is_xlsx)

    def _on_browse_xlsx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select filled manifold inspection sheet",
            self._project_root,
            "Spreadsheets (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv)",
        )
        if path:
            self._import_xlsx_path = path
            self.edit_xlsx_path.setText(path)

    def _on_export_template(self) -> None:
        try:
            tpl_src = ensure_standard_template(self._config_dir)
            # Re-write with latest DataValidation dropdowns and instructions
            write_connections_workbook(tpl_src, [])
        except Exception as exc:
            QMessageBox.critical(self, "Export template", f"Could not build template:\n{exc}")
            return
        default_dst = os.path.join(self._project_root, "manifold_inspection_template.xlsx")
        dst, _ = QFileDialog.getSaveFileName(
            self,
            "Export blank manifold inspection Excel template",
            default_dst,
            "Excel Workbook (*.xlsx)",
        )
        if not dst:
            return
        if not dst.lower().endswith(".xlsx"):
            dst += ".xlsx"
        try:
            shutil.copy2(tpl_src, dst)
        except OSError as exc:
            QMessageBox.critical(self, "Export template", str(exc))
            return
        QMessageBox.information(
            self,
            "Template exported",
            f"Saved blank template to:\n{dst}\n\n"
            "It includes:\n"
            "• HOLE OPEN sheet with dropdowns for Manual (YES) and View (A–F, A-E, A-F, C-F)\n"
            "• HOW TO FILL instructions tab.",
        )

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
        if template == IMPORT_SPREADSHEET:
            if not self._import_xlsx_path or not os.path.isfile(self._import_xlsx_path):
                QMessageBox.warning(self, "Add manifold", "Select an Excel/CSV inspection sheet to import.")
                return
        elif template != BLANK_TEMPLATE:
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

        self.btn_create.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.status_lbl.setText("Creating folder and supporting files…")

        self._disk_worker = _ManifoldDiskWorker(
            self._config_dir,
            display,
            folder_id,
            template,
            self._import_xlsx_path,
            self,
        )
        self._disk_worker.succeeded.connect(
            partial(self._on_create_disk_done, display, folder_id)
        )
        self._disk_worker.failed.connect(self._on_create_disk_failed)
        self._disk_worker.finished.connect(self._disk_worker.deleteLater)
        self._disk_worker.start()

    def _on_create_disk_done(self, display: str, folder_id: str, rule_count: int) -> None:
        self._created_folder = folder_id
        self.created_label = display
        self.btn_create.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.btn_open_rules.setEnabled(True)
        self.btn_open_rois.setEnabled(True)
        self.status_lbl.setText(
            f"Created config/{folder_id}/ ({rule_count} rule(s)). "
            "Use the buttons below to load/edit Hole Connections and place Hole ROIs."
        )
        self._disk_worker = None
        QMessageBox.information(
            self,
            "Manifold created",
            f"{display}\n\nFolder: config/{folder_id}/\n"
            f"Rules loaded: {rule_count}\n\n"
            "Next steps:\n"
            "1. Click 'Edit / Load Hole Connections' if you need to load or adjust the Excel sheet.\n"
            "2. Click 'Place Hole ROIs' to draw the ellipses for Faces A–F from the rule dropdown.",
        )

    def _on_create_disk_failed(self, message: str) -> None:
        self.btn_create.setEnabled(True)
        self.btn_close.setEnabled(True)
        self.status_lbl.setText("Creation failed; partial folder was cleaned up so you can retry.")
        self._disk_worker = None
        QMessageBox.critical(self, "Add manifold", message)

    def _on_open_rule_editor(self) -> None:
        if not self.created_label:
            return
        from rule_editor_ui import RuleEditorDialog

        dlg = RuleEditorDialog(
            self.created_label,
            self._config_dir,
            stylesheet=self._stylesheet,
            inspection_running=False,
            parent=self,
        )
        dlg.exec()

    def _on_open_roi_editor(self) -> None:
        if not self.created_label:
            return
        from roi_editor import RoiEditorDialog

        dlg = RoiEditorDialog(
            self.created_label,
            self._config_dir,
            self._cameras,
            None,
            None,
            self._stylesheet,
            self,
            setup_mode=True,
        )
        dlg.exec()

    def closeEvent(self, event) -> None:
        if self._disk_worker is not None and self._disk_worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

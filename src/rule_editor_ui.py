"""Type-in editor and spreadsheet dry-run for hole connections."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt

from config_loader import manifold_folder_for_label
from logic_engine import parse_face_to_faces
from connectivity_rules_io import (
    ConnectionRow,
    RulesDiff,
    carry_manual_checks,
    diff_rules,
    format_diff,
    hole_ids_for_face,
    inspection_rows_from_rules,
    load_rules_file,
    merge_connection_rows,
    normalize_hole_id,
    normalize_input_face,
    pair_exit_holes_and_faces,
    parse_spreadsheet,
    roi_names_by_face,
    rules_from_spreadsheet,
    save_rules_atomic,
    split_cell_list,
    uniquify_rule_ids,
    validate_rules,
    write_tree_workbook,
)

FACE_LETTERS = list("ABCDEF")
ROW_HEIGHT = 28
COL_MANUAL = 0
COL_INSERT = 1
COL_INSERT_VIEW = 2
COL_INSPECTION = 3
COL_EXIT_VIEW = 4


class _DryRunDialog(QDialog):
    def __init__(self, text: str, stylesheet: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review hole connections")
        self.setMinimumSize(560, 420)
        if stylesheet:
            self.setStyleSheet(stylesheet)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        hint = QLabel(
            "This replaces the working hole map. Confirm only if the list looks right."
        )
        hint.setWordWrap(True)
        hint.setObjectName("pageHint")
        layout.addWidget(hint)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(text)
        layout.addWidget(body, stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("pageGhost")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("Save hole connections")
        confirm.setObjectName("pagePrimary")
        confirm.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(confirm)
        layout.addLayout(row)
        cancel.setDefault(True)
        cancel.setAutoDefault(True)
        confirm.setAutoDefault(False)
        cancel.setFocus()


class RuleEditorDialog(QDialog):
    """Hole connections: one row per insert, same columns as the inspection sheet."""

    def __init__(
        self,
        manifold: str,
        config_dir: str,
        stylesheet: str = "",
        inspection_running: bool = False,
        available_faces: Optional[Set[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._manifold = manifold
        self._config_dir = config_dir
        self._folder = manifold_folder_for_label(manifold, config_dir) or "DALIA"
        self._path = os.path.normpath(
            os.path.join(config_dir, self._folder, "connectivity_rules.json")
        )
        self._inspection_running = inspection_running
        self._available = available_faces or set("ABCDEF")
        self._stylesheet = stylesheet
        self.saved = False
        self.setWindowTitle("Hole connections")
        self.setMinimumSize(920, 560)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        self._old_rules = load_rules_file(self._path)
        self._roi_names = roi_names_by_face(config_dir, self._folder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Hole connections")
        title.setObjectName("pageTitleMain")
        layout.addWidget(title)
        hint = QLabel(
            f"{manifold}  —  One row is one insert, the same as the inspection sheet. "
            "For Inspection and the second View are comma lists. "
            "Tick Manual to run that hole last: you press Pass or Fail, and there is no timer."
        )
        hint.setWordWrap(True)
        hint.setObjectName("pageHint")
        layout.addWidget(hint)

        if inspection_running:
            warn = QLabel("STOP inspection before saving. Cameras stay open.")
            warn.setStyleSheet("color: #8a5a12; font-weight: 600;")
            layout.addWidget(warn)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Manual",
            "Insert Rod",
            "View",
            "For Inspection",
            "View",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_MANUAL, QHeaderView.ResizeMode.ResizeToContents)
        for col in (COL_INSERT, COL_INSERT_VIEW, COL_INSPECTION, COL_EXIT_VIEW):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, stretch=1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add row")
        add_btn.setObjectName("pageSecondary")
        add_btn.clicked.connect(lambda: self._add_row())
        del_btn = QPushButton("Remove row")
        del_btn.setObjectName("pageSecondary")
        del_btn.clicked.connect(self._remove_row)
        load_btn = QPushButton("Load spreadsheet")
        load_btn.setObjectName("pageSecondary")
        load_btn.clicked.connect(self._load_spreadsheet)
        save_xlsx_btn = QPushButton("Save spreadsheet")
        save_xlsx_btn.setObjectName("pageSecondary")
        save_xlsx_btn.clicked.connect(self._save_spreadsheet)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(save_xlsx_btn)
        btn_row.addWidget(load_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        save_row = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("pageGhost")
        close_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Save hole connections")
        self._save_btn.setObjectName("pagePrimary")
        self._save_btn.clicked.connect(self._save)
        self._save_btn.setEnabled(not inspection_running)
        save_row.addStretch(1)
        save_row.addWidget(close_btn)
        save_row.addWidget(self._save_btn)
        layout.addLayout(save_row)

        self._fill_from_rules(self._old_rules)

    def _hole_choices(self, face: str) -> List[str]:
        names = list(hole_ids_for_face(self._old_rules, face))
        for hid in sorted(self._roi_names.get(face) or []):
            if hid not in names:
                names.append(hid)
        return names

    def _line(self, text: str) -> QLineEdit:
        edit = QLineEdit(text)
        edit.setEnabled(not self._inspection_running)
        edit.setFixedHeight(26)
        return edit

    def _add_row(self, item: Optional[Dict[str, str]] = None) -> None:
        item = item or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        manual = QCheckBox()
        manual.setToolTip(
            "YES on the sheet. This hole runs last. You press Pass or Fail. No timer."
        )
        manual.setChecked(str(item.get("manual") or "").strip().upper() == "YES")
        manual.setEnabled(not self._inspection_running)
        wrap = QWidget()
        wrap_layout = QHBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap_layout.addWidget(manual)
        wrap._manual_box = manual
        self.table.setCellWidget(r, COL_MANUAL, wrap)
        self.table.setCellWidget(r, COL_INSERT, self._line(item.get("insert", "")))
        self.table.setCellWidget(r, COL_INSERT_VIEW, self._line(item.get("insert_view", "A")))
        self.table.setCellWidget(r, COL_INSPECTION, self._line(item.get("inspection", "")))
        self.table.setCellWidget(r, COL_EXIT_VIEW, self._line(item.get("exit_view", "A")))
        self.table.setRowHeight(r, ROW_HEIGHT)

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)

    def _cell_text(self, row: int, col: int) -> str:
        widget = self.table.cellWidget(row, col)
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return ""

    def _manual_box(self, row: int) -> Optional[QCheckBox]:
        wrap = self.table.cellWidget(row, COL_MANUAL)
        box = getattr(wrap, "_manual_box", None)
        return box if isinstance(box, QCheckBox) else None

    def _rows_from_table(self) -> List[ConnectionRow]:
        rows: List[ConnectionRow] = []
        for r in range(self.table.rowCount()):
            box = self._manual_box(r)
            execution = "manual" if box is not None and box.isChecked() else "auto"
            insert = self._cell_text(r, COL_INSERT)
            insert_view = self._cell_text(r, COL_INSERT_VIEW)
            pairs = pair_exit_holes_and_faces(
                split_cell_list(self._cell_text(r, COL_INSPECTION)),
                split_cell_list(self._cell_text(r, COL_EXIT_VIEW)),
            )
            for hole, face in pairs:
                rows.append(ConnectionRow(
                    input_face=insert_view,
                    input_hole=insert,
                    output_face=face,
                    output_hole=hole,
                    execution=execution,
                ))
        return rows

    def _rules_from_table(self) -> List[Dict[str, Any]]:
        return merge_connection_rows(self._rows_from_table())

    def _fill_from_rules(self, rules: List[Dict[str, Any]]) -> None:
        self.table.setRowCount(0)
        sheet_rows = inspection_rows_from_rules(rules)
        if not sheet_rows:
            self._add_row()
            return
        for item in sheet_rows:
            self._add_row(item)

    def _save_spreadsheet(self) -> None:
        rules = self._rules_from_table()
        if not rules:
            QMessageBox.warning(
                self,
                "Save spreadsheet",
                "Add at least one insert hole and one light-out hole first.",
            )
            return
        start = os.path.join(self._config_dir, self._folder, "manifold_inspection.xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save spreadsheet",
            start,
            "Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            write_tree_workbook(path, rules)
        except Exception as exc:
            QMessageBox.warning(self, "Save spreadsheet", str(exc))
            return
        QMessageBox.information(
            self,
            "Save spreadsheet",
            "Saved the inspection sheet.\n\n"
            "One row is one insert. For Inspection and the second View are comma lists.\n"
            "Write YES in Manual when that hole should wait for Pass or Fail.",
        )

    def _load_spreadsheet(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load spreadsheet",
            "",
            "Spreadsheets (*.xlsx *.xlsm *.csv);;Excel (*.xlsx *.xlsm);;CSV (*.csv)",
        )
        if not path:
            return
        parsed = parse_spreadsheet(path)
        if parsed.errors and not parsed.rows:
            QMessageBox.warning(
                self,
                "Load spreadsheet",
                "\n".join(parsed.errors),
            )
            return
        rules, parsed = rules_from_spreadsheet(path)
        rules = carry_manual_checks(self._old_rules, rules)
        if parsed.errors and not rules:
            QMessageBox.warning(self, "Load spreadsheet", "\n".join(parsed.errors))
            return
        if parsed.errors:
            QMessageBox.information(
                self,
                "Load spreadsheet",
                "Some rows were skipped:\n" + "\n".join(parsed.errors[:12]),
            )
        diff = diff_rules(
            self._old_rules,
            rules,
            merged_from_rows=parsed.source_row_count,
            roi_names=self._roi_names,
            available_faces=self._available,
        )
        text = format_diff(diff)
        if parsed.headers:
            text = (
                "Headers: "
                + ", ".join(h for h in parsed.headers if str(h).strip())
                + "\n\n"
                + text
            )
        dlg = _DryRunDialog(text, self._stylesheet, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._fill_from_rules(rules)
        self._save_rules(rules, diff)

    def _save(self) -> None:
        if self._inspection_running:
            QMessageBox.warning(
                self,
                "Hole connections",
                "STOP inspection before saving hole connections.",
            )
            return
        rules = self._rules_from_table()
        errors = validate_rules(rules)
        if errors:
            QMessageBox.warning(self, "Hole connections", "\n".join(errors[:12]))
            return
        if not rules:
            QMessageBox.warning(self, "Hole connections", "Add at least one connection.")
            return
        typed_new = []
        seen_new = set()
        for row in self._rows_from_table():
            face = normalize_input_face(row.input_face)
            hole = normalize_hole_id(row.input_hole)
            letters = parse_face_to_faces(face) or ["A"]
            known = set()
            for letter in letters:
                known.update(self._hole_choices(letter))
            label = f"Face {face}: {hole}"
            if hole and hole not in known and label not in seen_new:
                seen_new.add(label)
                typed_new.append(label)
        if typed_new:
            go = QMessageBox.question(
                self,
                "New hole names",
                "These names are not on the current list. "
                "The ROI dropdown will show them; an ellipse may not exist yet.\n\n"
                + "\n".join(typed_new[:20]),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if go != QMessageBox.StandardButton.Save:
                return
        diff = diff_rules(
            self._old_rules,
            rules,
            merged_from_rows=self.table.rowCount(),
            roi_names=self._roi_names,
            available_faces=self._available,
        )
        dlg = _DryRunDialog(format_diff(diff), self._stylesheet, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_rules(rules, diff)

    def _save_rules(self, rules: List[Dict[str, Any]], diff: RulesDiff) -> None:
        try:
            save_rules_atomic(self._path, uniquify_rule_ids(rules), backup=True)
        except Exception as exc:
            QMessageBox.critical(self, "Hole connections", f"Could not write:\n{self._path}\n{exc}")
            return
        self._old_rules = uniquify_rule_ids(rules)
        self.saved = True
        extra = ""
        if diff.unknown_holes:
            extra = (
                "\n\nSome names have no ellipse yet. Place them with Place hole ROIs on camera setup."
            )
        QMessageBox.information(
            self,
            "Hole connections",
            f"Saved {diff.new_count} connections.\n"
            f"Guided steps: {diff.guided_after}."
            f"{extra}",
        )
        self.accept()

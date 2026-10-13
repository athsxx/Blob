"""Type-in editor and spreadsheet dry-run for hole connections."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
)

from config_loader import manifold_folder_for_label
from connectivity_rules_io import (
    ConnectionRow,
    OUTPUT_FACE_CHOICES,
    RulesDiff,
    diff_rules,
    format_diff,
    hole_ids_for_face,
    load_rules_file,
    merge_connection_rows,
    parse_spreadsheet,
    roi_names_by_face,
    rules_from_spreadsheet,
    rules_to_connection_rows,
    write_tree_workbook,
    save_rules_atomic,
    uniquify_rule_ids,
    validate_rules,
)

FACE_LETTERS = list("ABCDEF")
ROW_HEIGHT = 28
SHEET_COMBO_QSS = (
    "QComboBox { padding: 1px 6px; min-height: 20px; max-height: 26px; min-width: 0; }"
)


class SheetCombo(QComboBox):
    """Wheel scrolls the sheet. The list only changes while the dropdown is open."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(SHEET_COMBO_QSS)
        self.setFixedHeight(26)
        self.installEventFilter(self)

    def _scroll_sheet(self, event) -> None:
        widget = self.parent()
        table = None
        while widget is not None:
            if isinstance(widget, QTableWidget):
                table = widget
                break
            widget = widget.parent()
        if table is None:
            return
        bar = table.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.value() - int(event.angleDelta().y()))

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and not self.view().isVisible():
            self._scroll_sheet(event)
            return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        self._scroll_sheet(event)


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
    """Hole connections: one row = laser in + one light-out. Save writes connectivity_rules.json."""

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
            f"{manifold}  —  Each row is one light-out. Names must match the rings on the face pictures."
        )
        hint.setWordWrap(True)
        hint.setObjectName("pageHint")
        layout.addWidget(hint)

        if inspection_running:
            warn = QLabel("STOP inspection before saving. Cameras stay open.")
            warn.setStyleSheet("color: #8a5a12; font-weight: 600;")
            layout.addWidget(warn)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "Face in",
            "Hole in",
            "Face out",
            "Hole out",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setStyleSheet(SHEET_COMBO_QSS)
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

        rows = rules_to_connection_rows(self._old_rules)
        if rows:
            for row in rows:
                self._add_row(row)
        else:
            self._add_row()

    def _hole_choices(self, face: str) -> List[str]:
        names = list(hole_ids_for_face(self._old_rules, face))
        for hid in sorted(self._roi_names.get(face) or []):
            if hid not in names:
                names.append(hid)
        return names

    def _bind_sheet_combo(self, box: SheetCombo) -> None:
        edit = box.lineEdit()
        if edit is not None:
            edit.installEventFilter(box)

    def _face_combo(self, choices: List[str], current: str, on_face=None) -> QComboBox:
        box = SheetCombo()
        box.addItems(choices)
        idx = box.findText(current)
        if idx >= 0:
            box.setCurrentIndex(idx)
        elif current:
            box.addItem(current)
            box.setCurrentText(current)
        if on_face is not None:
            box.currentTextChanged.connect(on_face)
        return box

    def _hole_combo(self, face: str, current: str) -> QComboBox:
        box = SheetCombo()
        box.setEditable(True)
        self._bind_sheet_combo(box)
        box.addItems(self._hole_choices(face))
        if current:
            if box.findText(current) < 0:
                box.addItem(current)
            box.setCurrentText(current)
        return box

    def _add_row(self, row: Optional[ConnectionRow] = None) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        in_face = (row.input_face if row else "A") or "A"
        out_face = (row.output_face if row else "A") or "A"
        in_hole = row.input_hole if row else ""
        out_hole = row.output_hole if row else ""

        in_face_box = self._face_combo(FACE_LETTERS, in_face)
        out_face_box = self._face_combo(OUTPUT_FACE_CHOICES, out_face)
        in_hole_box = self._hole_combo(in_face, in_hole)
        out_hole_box = self._hole_combo(
            out_face[0] if out_face else "A",
            out_hole,
        )

        def _refill_in(_text: str) -> None:
            face = in_face_box.currentText()
            prev = in_hole_box.currentText()
            in_hole_box.blockSignals(True)
            in_hole_box.clear()
            in_hole_box.addItems(self._hole_choices(face))
            if prev:
                if in_hole_box.findText(prev) < 0:
                    in_hole_box.addItem(prev)
                in_hole_box.setCurrentText(prev)
            in_hole_box.blockSignals(False)

        def _refill_out(_text: str) -> None:
            face = out_face_box.currentText()
            letter = face[0] if face else "A"
            prev = out_hole_box.currentText()
            out_hole_box.blockSignals(True)
            out_hole_box.clear()
            out_hole_box.addItems(self._hole_choices(letter))
            if prev:
                if out_hole_box.findText(prev) < 0:
                    out_hole_box.addItem(prev)
                out_hole_box.setCurrentText(prev)
            out_hole_box.blockSignals(False)

        in_face_box.currentTextChanged.connect(_refill_in)
        out_face_box.currentTextChanged.connect(_refill_out)

        self.table.setCellWidget(r, 0, in_face_box)
        self.table.setCellWidget(r, 1, in_hole_box)
        self.table.setCellWidget(r, 2, out_face_box)
        self.table.setCellWidget(r, 3, out_hole_box)
        self.table.setRowHeight(r, ROW_HEIGHT)

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)

    def _combo_text(self, row: int, col: int) -> str:
        w = self.table.cellWidget(row, col)
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        item = self.table.item(row, col)
        return item.text().strip() if item else ""

    def _rows_from_table(self) -> List[ConnectionRow]:
        rows: List[ConnectionRow] = []
        for r in range(self.table.rowCount()):
            rows.append(ConnectionRow(
                input_face=self._combo_text(r, 0),
                input_hole=self._combo_text(r, 1),
                output_face=self._combo_text(r, 2),
                output_hole=self._combo_text(r, 3),
            ))
        return rows

    def _rules_from_table(self) -> List[Dict[str, Any]]:
        return merge_connection_rows(self._rows_from_table())

    def _replace_table(self, rows: List[ConnectionRow]) -> None:
        self.table.setRowCount(0)
        if not rows:
            self._add_row()
            return
        for row in rows:
            self._add_row(row)

    def _save_spreadsheet(self) -> None:
        rules = self._rules_from_table()
        if not rules:
            QMessageBox.warning(
                self,
                "Save spreadsheet",
                "Add at least one insert hole and one light-out hole first.",
            )
            return
        start = os.path.join(self._config_dir, self._folder, "hole_connections.xlsx")
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
            "Saved the hole sheet.\n\n"
            "Each row is one hole the laser goes into.\n"
            "Light 1, Light 2, and Light 3 on that row are where the light should appear.\n"
            "Leave a Light pair blank if you do not need it.",
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
        self._replace_table(rules_to_connection_rows(rules))
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
        for row in self._rows_from_table():
            face = row.input_face
            hole = row.input_hole
            known = set(self._hole_choices(face))
            if hole and hole not in known:
                typed_new.append(f"Face {face}: {hole}")
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

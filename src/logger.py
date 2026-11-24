"""
Logging Module

Organized per-session inspection logging + master append-only CSV report + system events.
Each InspectionLogger session (one per inspection run / process) creates its own isolated
folder under `logs/sessions/<YYYY-MM-DD>_S<NNN>_<ItemCode>_<ProductionNo>/` containing:
- `session_info.json`   (Operator metadata: ItemCode, ProductionNumber, SalaryCode, Manifold, Mode, timestamps, PASS/FAIL summary)
- `inspection_log.csv`  (That session's individual hole pass/fail report)
- `system.log`          (Session-specific system events)
while also appending to the master `logs/inspection_report.csv` for historical roll-ups.
"""

import csv
import json
import logging
import os
import queue
import re
from datetime import datetime
from threading import Thread
from typing import Any, Dict, Optional

LOG_DIR = "logs"
SESSIONS_SUBDIR = "sessions"
REPORT_NAME = "inspection_report.csv"
SESSION_REPORT_NAME = "inspection_log.csv"
SESSION_META_NAME = "session_info.json"
SESSION_SEQ_NAME = "session_seq.json"
DATE_FMT = "%Y-%m-%d"
ENGLISH_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
CSV_COLUMNS = [
    "Date",
    "Day",
    "Time",
    "Session",
    "ItemCode",
    "ProductionNumber",
    "SalaryCode",
    "Manifold",
    "Mode",
    "RuleID",
    "Result",
    "Input",
    "Expected",
    "Detected",
    "Missing",
]


def _excel_safe(text: str) -> str:
    if text and text[0] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def _safe_slug(text: str, fallback: str = "") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text or "").strip()).strip("_")
    return cleaned[:40] if cleaned else fallback


def _realign_csv_row(header: list, row: list) -> list:
    """Map a row onto the current columns.

    A master report can hold two shapes under the pre-operator header:
    a short row written before ItemCode/ProductionNumber/SalaryCode/Manifold/Mode
    existed, and a full-width row the new logger appended before the header was
    rewritten. Mapping that wide row through the short header stores the item
    code in RuleID and drops the real pass/fail. Wide rows are already in the
    current column order.
    """
    names = list(header or [])
    if names:
        names[0] = str(names[0]).lstrip("\ufeff")
    values = list(row)
    if len(names) < len(CSV_COLUMNS) and len(values) >= len(CSV_COLUMNS):
        return values[: len(CSV_COLUMNS)]
    padded = values + [""] * max(0, len(names) - len(values))
    by_name = {
        name: padded[index] if index < len(padded) else ""
        for index, name in enumerate(names)
    }
    return [by_name.get(column, "") for column in CSV_COLUMNS]


def _join_holes(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return _excel_safe(value)
    return "|".join(_excel_safe(str(item)) for item in value)


def _format_time(timestamp: datetime) -> str:
    return timestamp.strftime("%H:%M:%S.") + f"{timestamp.microsecond // 1000:03d}"


def _next_session(log_dir: str) -> int:
    path = os.path.join(log_dir, SESSION_SEQ_NAME)
    session_id = 1
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            session_id = int(data.get("next", 1))
            if session_id < 1:
                session_id = 1
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            session_id = 1
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump({"next": session_id + 1}, handle)
        handle.write("\n")
    os.replace(tmp_path, path)
    return session_id


class InspectionLogger:
    def __init__(
        self,
        log_dir: str = LOG_DIR,
        operator_info: Optional[Dict[str, str]] = None,
    ):
        self.log_dir = os.path.abspath(log_dir)
        os.makedirs(self.log_dir, exist_ok=True)

        self.started_at = datetime.now()
        self.session_id = _next_session(self.log_dir)
        self._meta: Dict[str, str] = {
            "item_code": "",
            "production_number": "",
            "salary_code": "",
            "manifold": "",
            "mode": "",
        }
        if operator_info:
            for k in self._meta:
                if k in operator_info and operator_info[k] is not None:
                    self._meta[k] = str(operator_info[k]).strip()

        self._pass_count = 0
        self._fail_count = 0

        # Dedicated per-session directory: logs/sessions/YYYY-MM-DD_HHMMSS_S001/
        sessions_root = os.path.join(self.log_dir, SESSIONS_SUBDIR)
        os.makedirs(sessions_root, exist_ok=True)
        folder_name = self._build_session_folder_name()
        self.session_dir = os.path.join(sessions_root, folder_name)
        os.makedirs(self.session_dir, exist_ok=True)
        self.session_csv_path = os.path.join(self.session_dir, SESSION_REPORT_NAME)
        self.session_meta_path = os.path.join(self.session_dir, SESSION_META_NAME)
        self.session_sys_log_path = os.path.join(self.session_dir, "system.log")

        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = False

        self.worker_thread = Thread(target=self._writer_loop, daemon=True)
        self.worker_thread.start()

        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[
                    logging.FileHandler(os.path.join(self.log_dir, "system.log"), encoding="utf-8"),
                    logging.StreamHandler(),
                ],
            )
        self.sys_log = logging.getLogger("System")
        self._session_file_handler = logging.FileHandler(self.session_sys_log_path, encoding="utf-8")
        self._session_file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        )
        self.sys_log.addHandler(self._session_file_handler)

        self._write_session_meta(status="OPEN")

        self.log_queue.put({
            "type": "inspection",
            "data": {
                "rule_id": "START",
                "result": "SESSION",
                "input_hole": "",
                "expected_outputs": [],
                "detected_outputs": [],
                "missing_outputs": [],
            },
            "timestamp": self.started_at,
            "session": self.session_id,
            "meta": dict(self._meta),
        })
        self.log_system("INFO", f"Session {self.session_id} opened -> {self.session_dir}")

    def _build_session_folder_name(self) -> str:
        stamp = self.started_at.strftime("%Y-%m-%d_%H%M%S")
        parts = [stamp, f"S{self.session_id:03d}"]
        item_slug = _safe_slug(self._meta.get("item_code", ""))
        prod_slug = _safe_slug(self._meta.get("production_number", ""))
        if item_slug:
            parts.append(item_slug)
        if prod_slug:
            parts.append(prod_slug)
        return "_".join(parts)

    def set_session_metadata(
        self,
        item_code: str = "",
        production_number: str = "",
        salary_code: str = "",
        manifold: str = "",
        mode: str = "",
    ) -> None:
        """Update session metadata once operator fills in Job/Operator details on setup screen."""
        self._meta["item_code"] = str(item_code or "").strip()
        self._meta["production_number"] = str(production_number or "").strip()
        self._meta["salary_code"] = str(salary_code or "").strip()
        if manifold:
            self._meta["manifold"] = str(manifold).strip()
        if mode:
            self._meta["mode"] = str(mode).strip()
        self._write_session_meta(status="ACTIVE")
        self.log_system(
            "INFO",
            f"Session {self.session_id} metadata: "
            f"ItemCode={self._meta['item_code']!r} "
            f"ProductionNumber={self._meta['production_number']!r} "
            f"SalaryCode={self._meta['salary_code']!r} "
            f"Manifold={self._meta['manifold']!r} "
            f"Mode={self._meta['mode']!r}",
        )

    def _write_session_meta(self, status: str = "ACTIVE") -> None:
        payload = {
            "session_id": self.session_id,
            "status": status,
            "date": self.started_at.strftime(DATE_FMT),
            "day": ENGLISH_DAYS[self.started_at.weekday()],
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "item_code": self._meta.get("item_code", ""),
            "production_number": self._meta.get("production_number", ""),
            "salary_code": self._meta.get("salary_code", ""),
            "manifold": self._meta.get("manifold", ""),
            "mode": self._meta.get("mode", ""),
            "pass_count": self._pass_count,
            "fail_count": self._fail_count,
            "session_csv": self.session_csv_path,
        }
        tmp = self.session_meta_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp, self.session_meta_path)
        except OSError:
            pass

    def log_inspection(self, result: Dict[str, Any]):
        """Log a hole decision. Intensity and eval time are ignored."""
        res_str = str((result or {}).get("result", "")).upper()
        if res_str == "PASS":
            self._pass_count += 1
        elif res_str == "FAIL":
            self._fail_count += 1
        self._write_session_meta(status="ACTIVE")
        self.log_queue.put({
            "type": "inspection",
            "data": result,
            "timestamp": datetime.now(),
            "session": self.session_id,
            "meta": dict(self._meta),
        })

    def log_system(self, level: str, message: str):
        """Log a system event (INFO, WARN, ERROR)."""
        self.sys_log.log(getattr(logging, level.upper()), message)

    def stop(self):
        """Stop the logging worker after draining queued rows."""
        self.stop_event = True
        self.log_queue.put(None)
        self.worker_thread.join(timeout=2.0)
        self._write_session_meta(status="CLOSED")
        try:
            self.sys_log.removeHandler(self._session_file_handler)
            self._session_file_handler.close()
        except Exception:
            pass

    def _writer_loop(self):
        """Background thread to write the hole report to disk."""
        while not self.stop_event or not self.log_queue.empty():
            try:
                item = self.log_queue.get(timeout=0.5)
                if item is None:
                    continue
                self._write_inspection(item)
            except queue.Empty:
                continue
            except Exception as exc:
                print(f"Logging error: {exc}")

    def _migrate_csv_header(self, csv_path: str) -> None:
        """Rewrite a pre-operator-column report so new rows do not shift RuleID/Result.

        Reports created before ItemCode/ProductionNumber/SalaryCode/Manifold/Mode
        keep the old header. Appending a wider row then stores the pass/fail under
        the wrong column.
        """
        if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
            return
        with open(csv_path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header:
                return
            header = list(header)
            header[0] = str(header[0]).lstrip("\ufeff")
            if header == CSV_COLUMNS:
                return
            old_rows = list(reader)
        aligned = [_realign_csv_row(header, old) for old in old_rows]
        tmp = csv_path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            writer.writerows(aligned)
        os.replace(tmp, csv_path)

    def _append_csv_row(self, csv_path: str, row: list) -> None:
        try:
            self._migrate_csv_header(csv_path)
        except OSError as exc:
            print(f"Logging error: could not realign {csv_path}: {exc}")
        write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(CSV_COLUMNS)
            writer.writerow(row)

    def _write_inspection(self, item: Dict[str, Any]) -> None:
        if item.get("type") != "inspection":
            return
        timestamp = item["timestamp"]
        data = item.get("data") or {}
        meta = item.get("meta") or self._meta
        row = [
            timestamp.strftime(DATE_FMT),
            ENGLISH_DAYS[timestamp.weekday()],
            _format_time(timestamp),
            item.get("session", self.session_id),
            _excel_safe(str(meta.get("item_code", ""))),
            _excel_safe(str(meta.get("production_number", ""))),
            _excel_safe(str(meta.get("salary_code", ""))),
            _excel_safe(str(meta.get("manifold", ""))),
            _excel_safe(str(meta.get("mode", ""))),
            _excel_safe(str(data.get("rule_id", ""))),
            _excel_safe(str(data.get("result", ""))),
            _excel_safe(str(data.get("input_hole", ""))),
            _join_holes(data.get("expected_outputs", [])),
            _join_holes(data.get("detected_outputs", [])),
            _join_holes(data.get("missing_outputs", [])),
        ]
        # 1. Master append-only log (logs/inspection_report.csv)
        master_csv_path = os.path.join(self.log_dir, REPORT_NAME)
        self._append_csv_row(master_csv_path, row)
        # 2. Dedicated per-session log (logs/sessions/<session>/inspection_log.csv)
        self._append_csv_row(self.session_csv_path, row)


_logger = None


def get_logger(log_dir: str = LOG_DIR) -> InspectionLogger:
    global _logger
    if _logger is None:
        _logger = InspectionLogger(log_dir)
    return _logger

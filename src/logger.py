"""
Logging Module

Append-only hole pass/fail report plus system events.
Each InspectionLogger open (one per main.py process) is the next session.
"""

import csv
import json
import logging
import os
import queue
from datetime import datetime
from threading import Thread
from typing import Any, Dict

LOG_DIR = "logs"
REPORT_NAME = "inspection_report.csv"
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
    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self.session_id = _next_session(log_dir)
        self.log_queue: queue.Queue = queue.Queue()
        self.stop_event = False

        self.worker_thread = Thread(target=self._writer_loop, daemon=True)
        self.worker_thread.start()

        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s [%(levelname)s] %(message)s",
                handlers=[
                    logging.FileHandler(os.path.join(log_dir, "system.log")),
                    logging.StreamHandler(),
                ],
            )
        self.sys_log = logging.getLogger("System")

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
            "timestamp": datetime.now(),
            "session": self.session_id,
        })
        self.log_system("INFO", f"Session {self.session_id} opened")

    def log_inspection(self, result: Dict[str, Any]):
        """Log a hole decision. Intensity and eval time are ignored."""
        self.log_queue.put({
            "type": "inspection",
            "data": result,
            "timestamp": datetime.now(),
            "session": self.session_id,
        })

    def log_system(self, level: str, message: str):
        """Log a system event (INFO, WARN, ERROR)."""
        self.sys_log.log(getattr(logging, level.upper()), message)

    def stop(self):
        """Stop the logging worker after draining queued rows."""
        self.stop_event = True
        self.log_queue.put(None)
        self.worker_thread.join(timeout=2.0)

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

    def _write_inspection(self, item: Dict[str, Any]) -> None:
        if item.get("type") != "inspection":
            return
        timestamp = item["timestamp"]
        data = item.get("data") or {}
        csv_path = os.path.join(self.log_dir, REPORT_NAME)
        write_header = (not os.path.exists(csv_path)) or os.path.getsize(csv_path) == 0
        with open(csv_path, "a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if write_header:
                writer.writerow(CSV_COLUMNS)
            writer.writerow([
                timestamp.strftime(DATE_FMT),
                ENGLISH_DAYS[timestamp.weekday()],
                _format_time(timestamp),
                item.get("session", self.session_id),
                _excel_safe(str(data.get("rule_id", ""))),
                _excel_safe(str(data.get("result", ""))),
                _excel_safe(str(data.get("input_hole", ""))),
                _join_holes(data.get("expected_outputs", [])),
                _join_holes(data.get("detected_outputs", [])),
                _join_holes(data.get("missing_outputs", [])),
            ])


_logger = None


def get_logger(log_dir: str = LOG_DIR) -> InspectionLogger:
    global _logger
    if _logger is None:
        _logger = InspectionLogger(log_dir)
    return _logger

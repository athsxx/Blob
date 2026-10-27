"""Unified hole report: one CSV, session per process, pass/fail only."""
import csv
import os
import re
import sys
import tempfile
import unittest
from datetime import date

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from logger import InspectionLogger  # noqa: E402

REPORT_NAME = "inspection_report.csv"
ENGLISH_DAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
COLUMNS = [
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
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")


def _read_report(log_dir):
    path = os.path.join(log_dir, REPORT_NAME)
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _open_logger(log_dir):
    logger = InspectionLogger(log_dir)
    return logger


class InspectionLogTests(unittest.TestCase):
    def test_first_open_writes_session_start_with_date_day_and_time(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logger = _open_logger(log_dir)
            logger.stop()
            rows = _read_report(log_dir)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row.keys()), COLUMNS)
        self.assertEqual(row["Session"], "1")
        self.assertEqual(row["RuleID"], "START")
        self.assertEqual(row["Result"], "SESSION")
        self.assertEqual(row["Date"], date.today().isoformat())
        self.assertEqual(row["Day"], ENGLISH_DAYS[date.today().weekday()])
        self.assertRegex(row["Time"], TIME_RE)

    def test_second_open_is_session_two(self):
        with tempfile.TemporaryDirectory() as log_dir:
            first = _open_logger(log_dir)
            first.stop()
            second = _open_logger(log_dir)
            second.stop()
            rows = _read_report(log_dir)
        self.assertEqual([row["Session"] for row in rows], ["1", "2"])
        self.assertEqual([row["RuleID"] for row in rows], ["START", "START"])
        self.assertEqual([row["Result"] for row in rows], ["SESSION", "SESSION"])

    def test_pass_and_fail_keep_holes_and_omit_intensity(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logger = _open_logger(log_dir)
            logger.log_inspection({
                "rule_id": "FACE_A_A1",
                "result": "PASS",
                "input_hole": "A_A1",
                "expected_outputs": ["B_B1"],
                "detected_outputs": ["B_B1"],
                "missing_outputs": [],
                "evaluation_time_ms": 123.4,
                "intensity": 200,
            })
            logger.stop()
            second = _open_logger(log_dir)
            second.log_inspection({
                "rule_id": "FACE_A_A2",
                "result": "FAIL",
                "input_hole": "A_A2",
                "expected_outputs": ["C_C1", "D_D1"],
                "detected_outputs": ["C_C1"],
                "missing_outputs": ["D_D1"],
                "intensity": 99,
            })
            second.stop()
            report_path = os.path.join(log_dir, REPORT_NAME)
            with open(report_path, encoding="utf-8") as handle:
                raw = handle.read()
            rows = _read_report(log_dir)

        self.assertNotIn("intensity", raw.lower())
        self.assertNotIn("EvalTimeMs", raw)
        self.assertEqual(len(rows), 4)
        passed = rows[1]
        failed = rows[3]
        self.assertEqual(passed["Session"], "1")
        self.assertEqual(passed["RuleID"], "FACE_A_A1")
        self.assertEqual(passed["Result"], "PASS")
        self.assertEqual(passed["Input"], "A_A1")
        self.assertEqual(passed["Expected"], "B_B1")
        self.assertEqual(passed["Detected"], "B_B1")
        self.assertEqual(passed["Missing"], "")
        self.assertEqual(failed["Session"], "2")
        self.assertEqual(failed["RuleID"], "FACE_A_A2")
        self.assertEqual(failed["Result"], "FAIL")
        self.assertEqual(failed["Input"], "A_A2")
        self.assertEqual(failed["Expected"], "C_C1|D_D1")
        self.assertEqual(failed["Detected"], "C_C1")
        self.assertEqual(failed["Missing"], "D_D1")

    def test_formula_like_hole_id_is_prefixed(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logger = _open_logger(log_dir)
            logger.log_inspection({
                "rule_id": "FACE_A_X",
                "result": "FAIL",
                "input_hole": "=A1",
                "expected_outputs": ["+B1"],
                "detected_outputs": [],
                "missing_outputs": ["@C1"],
            })
            logger.stop()
            rows = _read_report(log_dir)
        hole = rows[1]
        self.assertEqual(hole["Input"], "'=A1")
        self.assertEqual(hole["Expected"], "'+B1")
        self.assertEqual(hole["Missing"], "'@C1")


if __name__ == "__main__":
    unittest.main()

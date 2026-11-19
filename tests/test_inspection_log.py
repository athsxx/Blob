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

    def test_per_session_folder_and_operator_metadata_are_recorded(self):
        import json

        with tempfile.TemporaryDirectory() as log_dir:
            s1 = _open_logger(log_dir)
            s1.set_session_metadata(
                item_code="IC-9001",
                production_number="PN-2026-077",
                salary_code="SAL-442",
                manifold="DALIA",
                mode="sequential",
            )
            s1.log_inspection({
                "rule_id": "FACE_A_A1",
                "result": "PASS",
                "input_hole": "A_A1",
                "expected_outputs": ["F_A2"],
                "detected_outputs": ["F_A2"],
                "missing_outputs": [],
            })
            s1.stop()

            s2 = _open_logger(log_dir)
            s2.set_session_metadata(
                item_code="IC-9002",
                production_number="PN-2026-078",
                salary_code="SAL-518",
                manifold="DALIA",
                mode="custom",
            )
            s2.log_inspection({
                "rule_id": "FACE_B_B17",
                "result": "FAIL",
                "input_hole": "B_B17",
                "expected_outputs": ["C_B18"],
                "detected_outputs": [],
                "missing_outputs": ["C_B18"],
            })
            s2.stop()

            # Separate per-session folders exist
            self.assertNotEqual(s1.session_dir, s2.session_dir)
            self.assertTrue(os.path.isfile(s1.session_csv_path))
            self.assertTrue(os.path.isfile(s2.session_csv_path))
            self.assertTrue(os.path.isfile(s1.session_meta_path))
            self.assertTrue(os.path.isfile(s2.session_meta_path))

            with open(s1.session_meta_path, encoding="utf-8") as f:
                meta1 = json.load(f)
            self.assertEqual(meta1["item_code"], "IC-9001")
            self.assertEqual(meta1["production_number"], "PN-2026-077")
            self.assertEqual(meta1["salary_code"], "SAL-442")
            self.assertEqual(meta1["pass_count"], 1)
            self.assertEqual(meta1["fail_count"], 0)
            self.assertEqual(meta1["status"], "CLOSED")

            with open(s1.session_csv_path, newline="", encoding="utf-8") as f:
                s1_rows = list(csv.DictReader(f))
            self.assertEqual(len(s1_rows), 2)
            self.assertEqual(s1_rows[1]["ItemCode"], "IC-9001")
            self.assertEqual(s1_rows[1]["ProductionNumber"], "PN-2026-077")
            self.assertEqual(s1_rows[1]["SalaryCode"], "SAL-442")
            self.assertEqual(s1_rows[1]["Manifold"], "DALIA")
            self.assertEqual(s1_rows[1]["Mode"], "sequential")

            with open(s2.session_csv_path, newline="", encoding="utf-8") as f:
                s2_rows = list(csv.DictReader(f))
            self.assertEqual(len(s2_rows), 2)
            self.assertEqual(s2_rows[1]["ItemCode"], "IC-9002")
            self.assertEqual(s2_rows[1]["ProductionNumber"], "PN-2026-078")
            self.assertEqual(s2_rows[1]["SalaryCode"], "SAL-518")


if __name__ == "__main__":
    unittest.main()

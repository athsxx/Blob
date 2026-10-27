"""Manual checks: saved on the rule, run last, and the cameras do not decide them."""
import json
import os
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from connectivity_rules_io import (  # noqa: E402
    ConnectionRow,
    carry_manual_checks,
    merge_connection_rows,
    normalize_execution,
    rules_from_spreadsheet,
    write_connections_workbook,
    inject_inspection_template,
)
from logic_engine import LogicEngine  # noqa: E402


def _rule(face, hole, exits, execution="auto"):
    return {
        "rule_id": f"FACE_{face}_{hole}",
        "input": {"face": face, "hole_id": hole},
        "expected_outputs": [
            {"face": out_face, "hole_id": out_hole, "mandatory": True}
            for out_face, out_hole in exits
        ],
        "logic": "AND",
        "execution": execution,
        "timing": {"max_delay_ms": 250, "min_stable_frames": 3},
    }


class ExecutionTests(unittest.TestCase):
    def test_new_manifold_gets_the_template_and_rules_built_from_it(self):
        with tempfile.TemporaryDirectory() as config_dir:
            template = os.path.join(config_dir, "template")
            os.makedirs(template)
            sheet = os.path.join(template, "manifold_inspection.xlsx")
            write_connections_workbook(
                sheet,
                [_rule("B", "A13", [("B", "A14")], "manual")],
            )
            dest = os.path.join(config_dir, "LINE_B")
            count = inject_inspection_template(dest, config_dir)
            self.assertEqual(count, 1)
            self.assertTrue(os.path.isfile(os.path.join(dest, "manifold_inspection.xlsx")))
            with open(os.path.join(dest, "connectivity_rules.json"), encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["rules"][0]["execution"], "manual")
            self.assertEqual(saved["rules"][0]["input"]["hole_id"], "A13")
        rules = [
            _rule("A_F", "A14", [("B", "SEC. M-M"), ("B", "A13")], "manual"),
            _rule("A", "A1", [("F", "A2")], "auto"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "manifold_inspection.xlsx")
            write_connections_workbook(path, rules)
            loaded, parsed = rules_from_spreadsheet(path)
        self.assertEqual(parsed.errors, [])
        by_hole = {rule["input"]["hole_id"]: rule for rule in loaded}
        self.assertEqual(by_hole["A14"]["execution"], "manual")
        self.assertEqual(
            [out["hole_id"] for out in by_hole["A14"]["expected_outputs"]],
            ["SEC. M-M", "A13"],
        )
        self.assertEqual(by_hole["A1"]["execution"], "auto")
        self.assertEqual(by_hole["A14"]["input"]["face"], "A_F")
        self.assertEqual(normalize_execution(None), "auto")
        self.assertEqual(normalize_execution("MANUAL"), "manual")
        self.assertEqual(normalize_execution("nope"), "auto")

    def test_one_ticked_light_out_makes_the_hole_manual(self):
        rules = merge_connection_rows([
            ConnectionRow("B", "A13", "B", "SEC. M-M", execution="auto"),
            ConnectionRow("B", "A13", "A_F", "A14", execution="manual"),
        ])
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["execution"], "manual")
        self.assertEqual(len(rules[0]["expected_outputs"]), 2)

    def test_reload_keeps_manual_only_for_the_same_hole(self):
        previous = [
            _rule("B", "A13", [("B", "A14")], "manual"),
            _rule("A", "A1", [("F", "A2")], "auto"),
        ]
        incoming = [
            _rule("B", "A13", [("B", "A14"), ("A", "A7")]),
            _rule("C", "A4", [("B", "CENTRE HOLE")]),
        ]
        kept = carry_manual_checks(previous, incoming)
        by_hole = {rule["input"]["hole_id"]: rule["execution"] for rule in kept}
        self.assertEqual(by_hole["A13"], "manual")
        self.assertEqual(by_hole["A4"], "auto")
        self.assertNotIn("A1", by_hole)
        self.assertEqual(len(kept[0]["expected_outputs"]), 2)

    def test_manual_holes_run_after_every_automatic_hole(self):
        rules = [
            _rule("B", "B2", [("C", "B1")], "manual"),
            _rule("A", "A2", [("F", "A1")], "auto"),
            _rule("A", "A1", [("B", "A2")], "manual"),
            _rule("C", "C1", [("D", "A6")], "auto"),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "rules.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"rules": rules}, handle)
            engine = LogicEngine(path, stable_window_s=0)
        steps = engine.build_guided_sequence(set("ABCDEF"))
        order = [(step["input_hole"], step["execution"]) for step in steps]
        self.assertEqual(
            order,
            [("A2", "auto"), ("C1", "auto"), ("A1", "manual"), ("B2", "manual")],
        )

    def test_cameras_do_not_pass_a_manual_hole(self):
        manual = _rule("B", "A13", [("B", "A14")], "manual")
        auto = _rule("B", "A13", [("B", "A14")], "auto")
        for execution, rule in (("manual", manual), ("auto", auto)):
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "rules.json")
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump({"rules": [rule]}, handle)
                engine = LogicEngine(path, stable_window_s=0)
                engine.build_guided_sequence(set("ABCDEF"))
                engine.guided_mode = True
                engine.set_guided_step(0)
                engine.start()
                packet = {
                    "face": "B",
                    "camera_id": "CAM_B",
                    "detections": [{"hole_id": "A14", "laser": True, "confidence": 1}],
                    "health": {},
                }
                engine.update_state(packet)
                results = engine.update_state(packet)
            if execution == "manual":
                self.assertEqual(results, [])
            else:
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].result.value, "PASS")


if __name__ == "__main__":
    unittest.main()

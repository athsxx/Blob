"""Sheet Confirm renames matching rings and drops leftovers."""
import json
import os
import sys
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from connectivity_rules_io import (  # noqa: E402
    apply_roi_alignment,
    diff_rules,
    format_diff,
    plan_roi_alignment,
)


def _circle(name, x=10, y=20, w=5, h=5, angle=0):
    return {
        "name": name,
        "coords": [x, y, 5],
        "w": w,
        "h": h,
        "angle": angle,
    }


def _rule(face, hole, exits):
    return {
        "rule_id": f"FACE_{face}_{hole}",
        "input": {"face": face, "hole_id": hole},
        "expected_outputs": [
            {"face": out_face, "hole_id": out_hole, "mandatory": True}
            for out_face, out_hole in exits
        ],
        "logic": "AND",
        "execution": "auto",
    }


def _write_rois(folder, face_index, circles):
    path = os.path.join(folder, f"hole_positions_cam{face_index}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"calib_width": 320, "calib_height": 240, "circles": circles}, handle)
    return path


class RoiSheetAlignTests(unittest.TestCase):
    def test_renames_legacy_ring_and_keeps_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            coords = [214, 214, 5]
            _write_rois(folder, 0, [{
                "name": "Ø4_ROUND_HOLE",
                "coords": list(coords),
                "w": 5,
                "h": 5,
                "angle": 0,
            }])
            config_dir = os.path.dirname(folder)
            sub = os.path.basename(folder)
            rules = [_rule("A", "A1", [("A", "Ø4 (ROUND HOLE)")])]
            plan = plan_roi_alignment(config_dir, sub, rules)
            self.assertEqual(plan.renamed, [("A", "Ø4_ROUND_HOLE", "Ø4 (ROUND HOLE)")])
            apply_roi_alignment(plan)
            with open(os.path.join(folder, "hole_positions_cam0.json"), encoding="utf-8") as handle:
                saved = json.load(handle)
        ring = saved["circles"][0]
        self.assertEqual(ring["name"], "Ø4 (ROUND HOLE)")
        self.assertEqual(ring["coords"], coords)
        self.assertEqual(saved["calib_width"], 320)
        self.assertEqual(saved["calib_height"], 240)

    def test_drops_ring_with_no_sheet_hole(self):
        with tempfile.TemporaryDirectory() as folder:
            _write_rois(folder, 0, [
                _circle("A1"),
                _circle("LEFTOVER_HOLE", x=99, y=99),
            ])
            config_dir = os.path.dirname(folder)
            sub = os.path.basename(folder)
            rules = [_rule("A", "A1", [("B", "B1")])]
            plan = plan_roi_alignment(config_dir, sub, rules)
            self.assertEqual(plan.dropped, [("A", "LEFTOVER_HOLE")])
            apply_roi_alignment(plan)
            with open(os.path.join(folder, "hole_positions_cam0.json"), encoding="utf-8") as handle:
                saved = json.load(handle)
        names = [c["name"] for c in saved["circles"]]
        self.assertEqual(names, ["A1"])

    def test_does_not_steal_a_name_already_taken(self):
        with tempfile.TemporaryDirectory() as folder:
            _write_rois(folder, 0, [
                _circle("Ø4 (ROUND HOLE)", x=1, y=1),
                _circle("Ø4_ROUND_HOLE", x=2, y=2),
            ])
            config_dir = os.path.dirname(folder)
            sub = os.path.basename(folder)
            rules = [_rule("A", "A1", [("A", "Ø4 (ROUND HOLE)")])]
            plan = plan_roi_alignment(config_dir, sub, rules)
            self.assertEqual(plan.dropped, [("A", "Ø4_ROUND_HOLE")])
            self.assertEqual(plan.renamed, [])
            apply_roi_alignment(plan)
            with open(os.path.join(folder, "hole_positions_cam0.json"), encoding="utf-8") as handle:
                saved = json.load(handle)
        names = [c["name"] for c in saved["circles"]]
        self.assertEqual(names, ["Ø4 (ROUND HOLE)"])
        self.assertEqual(saved["circles"][0]["coords"], [1, 1, 5])

    def test_dry_run_lists_renames_and_drops(self):
        with tempfile.TemporaryDirectory() as folder:
            _write_rois(folder, 0, [
                _circle("Ø4_ROUND_HOLE"),
                _circle("GHOST"),
            ])
            config_dir = os.path.dirname(folder)
            sub = os.path.basename(folder)
            rules = [_rule("A", "A1", [("A", "Ø4 (ROUND HOLE)")])]
            plan = plan_roi_alignment(config_dir, sub, rules)
            diff = diff_rules([], rules, roi_names=plan.names_after)
            diff.roi_renames = list(plan.renamed)
            diff.roi_drops = list(plan.dropped)
            text = format_diff(diff)
        self.assertIn("Ø4_ROUND_HOLE → Ø4 (ROUND HOLE)", text)
        self.assertIn("GHOST", text)


if __name__ == "__main__":
    unittest.main()

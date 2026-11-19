"""End-to-end regression tests for DALIA inspection sheet fixes:
- Canonical hole key matching across cp1252 mojibake (Ã˜ -> Ø) and alias names
- Excel parser preserving all 74 rules (SEC. T4-T4 COUNTER & SEC. T-T CENTRE)
- Green laser false-positive rejection on white specular glare vs true green laser
- 5 fps stability / grace-period tolerance across 1-frame flicker
- Offscreen PyQt6 InstructionPanel.tree_lbl non-clipping across all 74 rules
- ManualInspectionSetupPage compound-face (A-E, A-F, C-F) visibility
- camera_port_map.json.template valid JSON
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

from camera_worker import CameraWorker, _hole_key  # noqa: E402
from connectivity_rules_io import (  # noqa: E402
    canonical_hole_key,
    normalize_hole_id,
    rules_from_spreadsheet,
)
from logic_engine import LogicEngine  # noqa: E402
from voice_assistant import format_hole_for_speech  # noqa: E402


class DaliaBugFixTests(unittest.TestCase):
    def test_canonical_hole_key_matches_mojibake_and_aliases(self):
        # cp1252 mojibake for Ø
        self.assertEqual(
            canonical_hole_key("Ã˜12.32 (SR. NO. 324)"),
            canonical_hole_key("Ø12.32 (SR. NO. 324)"),
        )
        self.assertEqual(
            _hole_key("Ã˜9.14 (SR. NO. 426 - A)"),
            _hole_key("Ø9.14 (SR. NO. 426) - A"),
        )
        # (A) and (B) suffixes on M1-M1 and N1-N1
        self.assertEqual(
            canonical_hole_key("SEC. M1-M1 (A)"),
            canonical_hole_key("SEC. M1-M1"),
        )
        self.assertEqual(
            canonical_hole_key("SEC. N1-N1 (B)"),
            canonical_hole_key("SEC. N1-N1"),
        )
        # LD-LD / LE-LE legacy names vs Ø6.5 names
        self.assertEqual(
            canonical_hole_key("ANGULAR HOLE (LD-LD)"),
            canonical_hole_key("Ø6.5 (SR. NO. 1185) LD-LD"),
        )
        self.assertEqual(
            canonical_hole_key("STRIGHT HOLE (LE-LE)"),
            canonical_hole_key("Ø6.5 (SR. NO. 1188) LE-LE"),
        )
        # Voice assistant repairs cp1252 mojibake
        self.assertIn("Diameter 4", format_hole_for_speech("Ã˜4 (ROUND HOLE)"))

    def test_final_dalia_excel_preserves_all_74_rules_including_t4_and_t_centre(self):
        excel_path = os.path.join(ROOT, "Pictures", "Final dalia_manifold_inspection.xlsx")
        rules, parsed = rules_from_spreadsheet(excel_path)
        self.assertEqual(parsed.errors, [])
        self.assertEqual(len(rules), 74)
        by_id = {r["rule_id"]: r for r in rules}
        self.assertIn("FACE_B_SEC. T-T CENTRE", by_id)
        self.assertIn("FACE_B_SEC. T4-T4 COUNTER", by_id)
        self.assertEqual(
            [o["hole_id"] for o in by_id["FACE_B_SEC. T-T CENTRE"]["expected_outputs"]],
            ["B11"],
        )
        self.assertEqual(
            [o["hole_id"] for o in by_id["FACE_B_SEC. T4-T4 COUNTER"]["expected_outputs"]],
            ["SEC. P-P"],
        )

    def test_laser_detector_rejects_white_glare_and_1px_noise_but_detects_true_green_laser(self):
        with tempfile.TemporaryDirectory() as tmp:
            roi_file = os.path.join(tmp, "hole_positions_cam1.json")
            with open(roi_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "calib_width": 200,
                        "calib_height": 200,
                        "circles": [{"name": "CENTRE HOLE", "coords": [100, 100, 50], "w": 50, "h": 50, "angle": 0}],
                    },
                    f,
                )
            worker = CameraWorker(
                usb_index=1,
                face="B",
                config_file=roi_file,
                result_queue=None,
                control_event=None,
                capture_settings={"log_dir": tmp},
            )
            worker.load_rois()
            worker._build_roi_masks(200, 200)
            roi = worker.rois[0]

            # Case 1: 1 noisy pale-green pixel + bright white glare patch (200, 200, 200)
            frame_glare = np.zeros((200, 200, 3), dtype=np.uint8)
            frame_glare[90:110, 90:110] = (200, 200, 200)  # white specular glare
            frame_glare[100, 100] = (40, 120, 40)  # 1 green noise pixel
            hsv = cv2.cvtColor(frame_glare, cv2.COLOR_BGR2HSV)
            green_mask = cv2.inRange(hsv, worker._lower_green, worker._upper_green)
            b, g, r = cv2.split(frame_glare)
            detected_glare, _, _, _ = worker.detect_green_laser_in_roi(green_mask, b, g, r, roi)
            self.assertFalse(detected_glare, "White glare + 1 green noise pixel must NOT trigger false positive")

            # Case 2: True green laser spot (5x5 bright green pixels: B=20, G=230, R=20)
            frame_laser = np.zeros((200, 200, 3), dtype=np.uint8)
            frame_laser[98:103, 98:103] = (20, 230, 20)
            hsv2 = cv2.cvtColor(frame_laser, cv2.COLOR_BGR2HSV)
            green_mask2 = cv2.inRange(hsv2, worker._lower_green, worker._upper_green)
            b2, g2, r2 = cv2.split(frame_laser)
            detected_laser, conf, px, _ = worker.detect_green_laser_in_roi(green_mask2, b2, g2, r2, roi)
            worker.trace.close()
            self.assertTrue(detected_laser, "True green laser spot must be detected")
            self.assertGreaterEqual(px, 8)
            self.assertGreaterEqual(conf, 0.5)

    def test_logic_engine_matches_mojibake_and_tolerates_5fps_1frame_flicker(self):
        rule = {
            "rule_id": "FACE_C_B13",
            "input": {"face": "C", "hole_id": "B13"},
            "expected_outputs": [
                {"face": "B", "hole_id": "Ã˜9.14 (SR. NO. 426 - A)", "mandatory": True},
            ],
            "logic": "AND",
            "execution": "auto",
        }
        with tempfile.TemporaryDirectory() as tmp:
            rpath = os.path.join(tmp, "rules.json")
            with open(rpath, "w", encoding="utf-8") as f:
                json.dump({"rules": [rule]}, f)
            engine = LogicEngine(rpath, stable_window_s=2.0)
            engine.build_guided_sequence(set("ABCDEF"))
            engine.guided_mode = True
            engine.set_guided_step(0)
            engine.start()

            on_pkt = {
                "face": "B",
                "camera_id": "CAM_B",
                "detections": [{"hole_id": "Ø9.14 (SR. NO. 426 - A)", "laser": True, "confidence": 0.9}],
                "health": {},
            }
            off_pkt = {
                "face": "B",
                "camera_id": "CAM_B",
                "detections": [{"hole_id": "Ø9.14 (SR. NO. 426 - A)", "laser": False, "confidence": 0.0}],
                "health": {},
            }

            # Simulate 5 fps (dt = 0.20s) with a 1-frame flicker causing 2 frames (0.40s) dropout
            t0 = 1000.0
            with patch("logic_engine.time.time") as mock_time:
                mock_time.return_value = t0
                self.assertEqual(engine.update_state(on_pkt), [])
                # Flicker dropout for 0.60s (within 0.85s grace period)
                mock_time.return_value = t0 + 0.60
                self.assertEqual(engine.update_state(off_pkt), [])
                # Recover at t0 + 0.80s
                mock_time.return_value = t0 + 0.80
                self.assertEqual(engine.update_state(on_pkt), [])
                # Reach 2.0s window at t0 + 2.05s -> PASS
                mock_time.return_value = t0 + 2.05
                res = engine.update_state(on_pkt)
                self.assertEqual(len(res), 1)
                self.assertEqual(res[0].result.value, "PASS")

    def test_port_map_templates_are_valid_json(self):
        for rel in ("config/camera_port_map.json.template", "Pictures/camera_port_map.json.template"):
            path = os.path.join(ROOT, rel)
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(len(data.get("entries", [])), 6)

    def test_ui_instruction_panel_never_clips_and_manual_page_includes_compound_faces(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from dashboard import DashboardWindow

        app = QApplication.instance() or QApplication([])
        win = DashboardWindow(
            total_rules=74,
            cameras=[],
            project_root=ROOT,
            config_dir=os.path.join(ROOT, "config"),
            cameras_file=os.path.join(ROOT, "config", "cameras.json"),
        )
        win.resize(1280, 800)
        win.stacked_widget.setCurrentIndex(4)
        win.show()
        app.processEvents()

        engine = LogicEngine(os.path.join(ROOT, "config", "DALIA", "connectivity_rules.json"))
        steps = engine.build_guided_sequence(set("ABCDEF"))
        self.assertEqual(len(steps), 74)

        clipped = []
        for idx, step in enumerate(steps):
            win.instruction_panel.show_step(step, len(steps))
            app.processEvents()
            lbl = win.instruction_panel.tree_lbl
            need = lbl.heightForWidth(lbl.width())
            if need > 0 and lbl.height() < need:
                clipped.append((idx + 1, step["rule_id"], lbl.height(), need))
        self.assertEqual(clipped, [], f"InstructionPanel.tree_lbl clipped on steps: {clipped}")

        # Verify ManualInspectionSetupPage shows compound-face rules (A_E, A_F, C_F)
        page = win.manual_setup_page
        page.set_manifold_items(["DALIA"], "DALIA")
        seen_rules = set()
        for f_idx in range(page.combo_face.count()):
            page.combo_face.setCurrentIndex(f_idx)
            app.processEvents()
            for r_idx in range(page.combo_rule.count()):
                rid = page.combo_rule.itemData(r_idx)
                if rid:
                    seen_rules.add(rid)
        self.assertEqual(len(seen_rules), 74, "All 74 rules (including compound faces) must be selectable")
        self.assertTrue(hasattr(page, "btn_add_manifold"))

        # Verify Header Manifold & Mode badges update including Item/Prod/Salary metadata
        win._on_mode_selected("sequential")
        win.manifold_page.edit_item_code.setText("IC-100")
        win.manifold_page.edit_prod_no.setText("PN-200")
        win.manifold_page.edit_salary_code.setText("SAL-300")
        win._on_manifold_selected("DALIA")
        self.assertIn("DALIA", win.header_manifold_badge.text())
        self.assertIn("ITEM: IC-100", win.header_manifold_badge.text())
        self.assertIn("PROD: PN-200", win.header_manifold_badge.text())
        self.assertIn("OP: SAL-300", win.header_manifold_badge.text())
        self.assertIn("SEQUENTIAL", win.header_mode_badge.text())
        self.assertEqual(
            win.operator_metadata,
            {"item_code": "IC-100", "production_number": "PN-200", "salary_code": "SAL-300"},
        )

        # Verify Camera Setup Readiness summary card populates
        win.prep_page.refresh_readiness(os.path.join(ROOT, "config"), "DALIA")
        self.assertIn("DALIA Readiness (74 rules)", win.prep_page.readiness_lbl.text())
        self.assertIn("Face A: 9/9", win.prep_page.readiness_lbl.text())

        # Verify StepListPanel collapse/expand toggle and InstructionPanel Prev/Next buttons
        self.assertEqual(win.step_list.width(), 276)
        win.step_list.toggle_collapsed()
        self.assertEqual(win.step_list.width(), 38)
        win.step_list.toggle_collapsed()
        self.assertEqual(win.step_list.width(), 276)
        self.assertTrue(hasattr(win.instruction_panel, "btn_prev_step"))
        self.assertTrue(hasattr(win.instruction_panel, "btn_next_step"))
        win.close()

    def test_new_manifold_supporting_files_and_per_manifold_setup_tracking(self):
        from config_loader import mark_setup_complete, setup_is_complete
        from manifold_setup_ui import IMPORT_SPREADSHEET, _ManifoldDiskWorker

        with tempfile.TemporaryDirectory() as tmp_cfg:
            # Copy capture_profile.json and Excel sheet into temp config
            with open(os.path.join(tmp_cfg, "capture_profile.json"), "w", encoding="utf-8") as f:
                json.dump({"width": 1280, "height": 800, "fps": 5, "fourcc": "MJPG", "backend": "dshow"}, f)
            mark_setup_complete(tmp_cfg, True, "DALIA")
            self.assertTrue(setup_is_complete(tmp_cfg, "DALIA"))

            excel_src = os.path.join(ROOT, "Pictures", "Final dalia_manifold_inspection.xlsx")
            worker = _ManifoldDiskWorker(
                config_dir=tmp_cfg,
                display="NEW_MANIFOLD_X",
                folder_id="NEW_MANIFOLD_X",
                template=IMPORT_SPREADSHEET,
                xlsx_path=excel_src,
            )
            counts = []
            errors = []
            worker.succeeded.connect(lambda n: counts.append(n))
            worker.failed.connect(lambda err: errors.append(err))
            worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(counts, [74])

            dest_dir = os.path.join(tmp_cfg, "NEW_MANIFOLD_X")
            # Verify all supporting files exist in config/NEW_MANIFOLD_X/
            self.assertTrue(os.path.isfile(os.path.join(dest_dir, "manifold_inspection.xlsx")))
            self.assertTrue(os.path.isfile(os.path.join(dest_dir, "connectivity_rules.json")))
            for idx in range(6):
                roi_file = os.path.join(dest_dir, f"hole_positions_cam{idx}.json")
                self.assertTrue(os.path.isfile(roi_file))
                with open(roi_file, "r", encoding="utf-8") as f:
                    roi_data = json.load(f)
                self.assertEqual(roi_data["calib_width"], 1280)
                self.assertEqual(roi_data["calib_height"], 800)
                self.assertEqual(roi_data["circles"], [])

            # DALIA stays setup_complete=True, while NEW_MANIFOLD_X requires setup until ROIs are placed
            self.assertTrue(setup_is_complete(tmp_cfg, "DALIA"))
            self.assertFalse(setup_is_complete(tmp_cfg, "NEW_MANIFOLD_X"))


if __name__ == "__main__":
    unittest.main()

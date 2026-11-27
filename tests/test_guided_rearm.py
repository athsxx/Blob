"""Leaving the rod in must not pass the next hole when it shares every exit.

DALIA insert A14 and insert A15 both expect light at SEC. M-M and A13.
Guided mode never looks at which hole the rod is in, so a still-lit A14
used to PASS A15 after the step change cleared in-memory detections and
the next camera frame put that light back.
"""
import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from logic_engine import (  # noqa: E402
    GUIDED_REARM_DARK_S,
    LogicEngine,
    rule_outputs_already_satisfied,
)

RULES = os.path.join(ROOT, "config", "DALIA", "connectivity_rules.json")


def _packet(face, holes):
    return {
        "face": face,
        "camera_id": f"CAM_{face}",
        "detections": [
            {
                "hole_id": hole_id,
                "laser": bool(lit),
                "confidence": 0.9 if lit else 0.0,
            }
            for hole_id, lit in holes.items()
        ],
        "health": {},
    }


class GuidedRearmTests(unittest.TestCase):
    def setUp(self):
        self.engine = LogicEngine(RULES, stable_window_s=2.0)
        self.engine.build_guided_sequence(set("ABCDEF"))
        self.engine.guided_mode = True
        self.index = {
            step["rule_id"]: i
            for i, step in enumerate(self.engine.get_guided_sequence())
        }

    def _rule(self, rule_id):
        return self.engine.rule_by_id[rule_id]

    def _exit_map(self, rule_id, lit):
        rule = self._rule(rule_id)
        return {output["hole_id"]: lit for output in rule["expected_outputs"]}

    def _feed(self, mock_time, at, face, holes):
        mock_time.return_value = at
        return self.engine.update_state(_packet(face, holes))

    def test_a14_light_does_not_pass_a15_until_the_exits_go_dark(self):
        a14 = self._rule("FACE_A_F_A14")
        a15 = self._rule("FACE_A_F_A15")
        self.assertTrue(rule_outputs_already_satisfied(a14, a15))
        self.assertEqual(
            self.index["FACE_A_F_A15"],
            self.index["FACE_A_F_A14"] + 1,
        )

        self.engine.set_guided_step(self.index["FACE_A_F_A14"])
        self.engine.start()
        lit = self._exit_map("FACE_A_F_A14", True)
        dark = self._exit_map("FACE_A_F_A14", False)

        with patch("logic_engine.time.time") as mock_time:
            self.assertEqual(self._feed(mock_time, 1000.0, "B", lit), [])
            passed = self._feed(mock_time, 1002.0, "B", lit)
            self.assertEqual([item.rule_id for item in passed], ["FACE_A_F_A14"])
            self.assertEqual(passed[0].result.value, "PASS")

            # Step change drops stored detections, then the same light comes back.
            self.engine.advance_guided_step()
            self.assertEqual(self.engine._active_rule_id, "FACE_A_F_A15")
            self.assertTrue(self.engine._stale_holes)

            self.assertEqual(self._feed(mock_time, 1002.2, "B", lit), [])
            # A single dropped frame must not look like the rod was removed.
            self.assertEqual(self._feed(mock_time, 1002.4, "B", dark), [])
            self.assertTrue(self.engine._stale_holes)
            self.assertEqual(self._feed(mock_time, 1005.0, "B", lit), [])
            self.assertTrue(self.engine._stale_holes)

            # Rod out long enough, then a real A15 insert.
            self.assertEqual(self._feed(mock_time, 1010.0, "B", dark), [])
            self.assertEqual(
                self._feed(mock_time, 1010.0 + GUIDED_REARM_DARK_S, "B", dark),
                [],
            )
            self.assertFalse(self.engine._stale_holes)
            self.assertEqual(self._feed(mock_time, 1010.6, "B", lit), [])
            passed = self._feed(mock_time, 1012.6, "B", lit)
            self.assertEqual([item.rule_id for item in passed], ["FACE_A_F_A15"])
            self.assertEqual(passed[0].result.value, "PASS")

    def test_shared_exit_still_passes_when_the_new_hole_has_its_own_light(self):
        """A15 then A18 share SEC. M-M, but A18 also needs A19. That unique
        exit is what proves the new rod went in, so the shared light may stay.
        """
        a15 = self._rule("FACE_A_F_A15")
        a18 = self._rule("FACE_A_F_A18")
        self.assertFalse(rule_outputs_already_satisfied(a15, a18))
        self.assertEqual(
            self.index["FACE_A_F_A18"],
            self.index["FACE_A_F_A15"] + 1,
        )

        self.engine.set_guided_step(self.index["FACE_A_F_A15"])
        self.engine.start()
        a15_lit = self._exit_map("FACE_A_F_A15", True)

        with patch("logic_engine.time.time") as mock_time:
            self._feed(mock_time, 2000.0, "B", a15_lit)
            passed = self._feed(mock_time, 2002.0, "B", a15_lit)
            self.assertEqual([item.rule_id for item in passed], ["FACE_A_F_A15"])

            self.engine.advance_guided_step()
            self.assertEqual(self.engine._active_rule_id, "FACE_A_F_A18")
            self.assertFalse(self.engine._stale_holes)

            a18_lit = self._exit_map("FACE_A_F_A18", True)
            self.assertIn("SEC. M-M", a18_lit)
            self.assertEqual(self._feed(mock_time, 2002.2, "B", a18_lit), [])
            passed = self._feed(mock_time, 2004.2, "B", a18_lit)
            self.assertEqual([item.rule_id for item in passed], ["FACE_A_F_A18"])
            self.assertEqual(passed[0].result.value, "PASS")


if __name__ == "__main__":
    unittest.main()

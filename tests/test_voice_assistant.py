"""Unit tests for offline voice guidance formatting and non-blocking announcer queue."""
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from voice_assistant import (  # noqa: E402
    VoiceAssistant,
    build_completion_speech,
    build_step_prompt_speech,
    build_step_result_speech,
    format_face_for_speech,
    format_hole_for_speech,
)


class VoiceAssistantTests(unittest.TestCase):
    def test_format_face_for_speech_handles_single_and_compound_faces(self):
        self.assertEqual(format_face_for_speech("A"), "Face A")
        self.assertEqual(format_face_for_speech("C_F"), "Face C or F")
        self.assertEqual(format_face_for_speech("B_OR_D"), "Face B or D")

    def test_format_hole_for_speech_normalizes_technical_hole_names(self):
        self.assertEqual(format_hole_for_speech("A1"), "A 1")
        self.assertEqual(format_hole_for_speech("SEC. M-M"), "Section M M")
        self.assertEqual(
            format_hole_for_speech("SEC. T3-T3 COUNTER"),
            "Section T 3 T 3 COUNTER",
        )
        self.assertEqual(
            format_hole_for_speech("Ø4 (OVAL HOLE) (SR. NO. 978)"),
            "Diameter 4, OVAL HOLE, Serial Number 978",
        )

    def test_build_step_prompt_and_result_speech(self):
        auto_step = {
            "step_num": 3,
            "input_face": "C_F",
            "input_hole": "A23",
            "execution": "auto",
        }
        self.assertEqual(
            build_step_prompt_speech(auto_step),
            "Rule 3. Please insert the laser in Face C or F, hole A 23.",
        )

        manual_step = {
            "step_num": 64,
            "input_face": "B",
            "input_hole": "SEC. Z3-Z3 COUNTER",
            "execution": "manual",
        }
        self.assertEqual(
            build_step_prompt_speech(manual_step),
            "Rule 64, manual check. Please insert the laser in Face B, hole Section Z 3 Z 3 COUNTER, and select Pass or Fail.",
        )

        self.assertEqual(
            build_step_result_speech(step_num=3, passed=True, has_next_step=True),
            "Rule 3 Passed. Please move to the next hole insert.",
        )
        self.assertEqual(
            build_step_result_speech(
                step_num=3, passed=False, has_next_step=True, timed_out=True
            ),
            "Rule 3 timed out and Failed. Please move to the next hole insert.",
        )

    def test_build_completion_speech_distinguishes_all_pass_from_failures(self):
        self.assertEqual(
            build_completion_speech(passed_count=74, failed_count=0),
            "Inspection complete. All 74 rules passed.",
        )
        self.assertEqual(
            build_completion_speech(passed_count=70, failed_count=4),
            "Inspection complete. 70 passed, 4 failed. Please review failed rules.",
        )

    def test_voice_assistant_toggle_and_shutdown_never_block(self):
        va = VoiceAssistant(enabled=False)
        self.assertFalse(va.enabled)
        va.speak("Should not queue when muted")
        self.assertTrue(va.toggle())
        self.assertFalse(va.toggle())
        va.shutdown()


if __name__ == "__main__":
    unittest.main()

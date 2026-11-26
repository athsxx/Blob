"""Corrupt USB frames must not become a laser hit.

Neon garbage and chroma stripes fail the quality gate and still satisfy the
green-laser check. Scoring them, or remembering them as the first good
picture, lets a guided hole PASS before the camera has a real frame.
"""
import json
import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from camera_worker import (  # noqa: E402
    CORRUPT_HOLD_AFTER_FRAMES,
    CORRUPT_HOLD_S,
    CameraWorker,
    _frame_quality,
    corrupt_frame_action,
)


def _stripe_frame(h=240, w=320):
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        band = (y // 8) % 3
        if band == 0:
            frame[y] = (20, 230, 20)
        elif band == 1:
            frame[y] = (200, 20, 200)
        else:
            frame[y] = (20, 20, 220)
    return frame


class CorruptFrameActionTests(unittest.TestCase):
    def test_no_good_frame_is_always_dropped(self):
        for streak in (1, 5, 50):
            self.assertEqual(
                corrupt_frame_action(
                    has_last_good=False,
                    corrupt_streak=streak,
                    hold_age_s=None,
                ),
                "drop",
            )

    def test_short_glitch_holds_last_good_then_goes_blind_for_good(self):
        """After the hold, later corrupt frames stay blind. They must not
        be scored, and the hold must not restart on the same outage."""
        hold_since = None
        seen = []
        for i in range(20):
            t = i * 0.2
            streak = i + 1
            age = None if hold_since is None else t - hold_since
            action = corrupt_frame_action(
                has_last_good=True,
                corrupt_streak=streak,
                hold_age_s=age,
            )
            seen.append(action)
            if action == "hold" and hold_since is None:
                hold_since = t
        self.assertEqual(seen[0], "blind")
        self.assertEqual(seen[CORRUPT_HOLD_AFTER_FRAMES - 1], "hold")
        self.assertIn("hold", seen)
        self.assertEqual(seen[-1], "blind")
        # Once the hold window has passed, scoring the frozen picture stops.
        expired = False
        for i, action in enumerate(seen):
            t = i * 0.2
            if hold_since is not None and t - hold_since >= CORRUPT_HOLD_S:
                expired = True
            if expired:
                self.assertEqual(action, "blind")
        self.assertTrue(expired)
        self.assertNotIn("drop", seen)

    def test_neon_stripes_fail_quality_and_still_look_like_a_laser(self):
        frame = _stripe_frame()
        quality, _stats = _frame_quality(frame)
        self.assertNotEqual(quality, "ok")
        with tempfile.TemporaryDirectory() as tmp:
            roi_file = os.path.join(tmp, "roi.json")
            with open(roi_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "calib_width": 320,
                        "calib_height": 240,
                        "circles": [{
                            "name": "A2",
                            "coords": [160, 120, 30],
                            "w": 30,
                            "h": 30,
                            "angle": 0,
                        }],
                    },
                    handle,
                )
            worker = CameraWorker(
                usb_index=0,
                face="F",
                config_file=roi_file,
                result_queue=None,
                control_event=None,
                capture_settings={"log_dir": tmp, "min_stable_frames": 2},
            )
            worker.load_rois()
            worker._build_roi_masks(240, 320)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            green = cv2.inRange(hsv, worker._lower_green, worker._upper_green)
            b, g, r = cv2.split(frame)
            detected, _conf, pixels, _intensity = worker.detect_green_laser_in_roi(
                green, b, g, r, worker.rois[0]
            )
            cleared = worker._no_laser_result()
            worker.trace.close()
        self.assertTrue(detected)
        self.assertGreaterEqual(pixels, 8)
        self.assertEqual(len(cleared["detections"]), 1)
        self.assertFalse(cleared["detections"][0]["laser"])
        self.assertEqual(cleared["detections"][0]["hole_id"], "A2")


if __name__ == "__main__":
    unittest.main()

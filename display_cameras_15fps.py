#!/usr/bin/env python3
"""
Open camera indices (default 0-5), attempt to set FPS to 15, and display.
On macOS, optionally configures AVFoundation devices by UID for more reliable FPS.
Press 'q' to quit.
"""

import argparse
import sys
import time
import threading
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_INDICES = [0, 1, 2, 3, 4, 5]
DEFAULT_FPS = 15.0
DEFAULT_WIDTH = 320
DEFAULT_HEIGHT = 240
DEFAULT_SCAN_MAX = 12
MAX_CONSECUTIVE_FAILS = 60
OPEN_DELAY_SEC = 0.2
DEFAULT_UIDS = [
    "0x1113000046d0843",  # Logitech C930e
    "0x11240002bdf0280",  # 1080P Web Camera
    "0x1112000046d085c",  # C922 Pro Stream Webcam
    "0x112200008060806",  # ABWB1002 PC WebCam (Arducam)
    "0x11210000bda5842",  # USB Camera
    "0x111100012242a25",  # USB CAMERA
]


def configure_macos_fps(uids: List[str], fps: float) -> None:
    try:
        import AVFoundation  # type: ignore
    except Exception:
        print("AVFoundation not available; skipping macOS device FPS configuration.")
        return

    devices = AVFoundation.AVCaptureDevice.devicesWithMediaType_(
        AVFoundation.AVMediaTypeVideo
    )
    uid_set = set(uids)

    for device in devices:
        if device.uniqueID() not in uid_set:
            continue

        print(f"Configuring FPS for {device.localizedName()} ({device.uniqueID()})")
        error = None
        locked, error = device.lockForConfiguration_(error)
        if not locked:
            print("  Could not lock device for configuration.")
            continue

        try:
            target = float(fps)
            best_format = None
            best_range = None
            formats = device.formats()
            for fmt in formats:
                ranges = fmt.videoSupportedFrameRateRanges()
                for r in ranges:
                    # Look for a range that includes target
                    if r.minFrameRate() - 0.1 <= target <= r.maxFrameRate() + 0.1:
                        best_format = fmt
                        best_range = r
                        break
                if best_format is not None:
                    break

            if best_format is None:
                print("  No format supports target FPS; leaving as-is.")
                continue

            device.setActiveFormat_(best_format)
            device.setActiveVideoMinFrameDuration_(best_range.minFrameDuration())
            device.setActiveVideoMaxFrameDuration_(best_range.minFrameDuration())
            print(
                f"  Set active format; frame rate range {best_range.minFrameRate()}-{best_range.maxFrameRate()}"
            )
        except Exception as e:
            print(f"  Failed to configure FPS: {e}")
        finally:
            device.unlockForConfiguration_()


def _backend_candidates() -> List[int]:
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def _configure_capture(cap: cv2.VideoCapture, fps: float, width: int, height: int) -> None:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


def _open_camera(
    idx: int, fps: float, width: int, height: int
) -> Tuple[Optional[cv2.VideoCapture], Optional[str]]:
    for backend in _backend_candidates():
        cap = cv2.VideoCapture(idx, backend)
        if not cap.isOpened():
            cap.release()
            continue

        _configure_capture(cap, fps, width, height)
        backend_name = "AVFOUNDATION" if backend == cv2.CAP_AVFOUNDATION else "ANY"
        return cap, backend_name

    return None, None


def _probe_camera(cap: cv2.VideoCapture, timeout_sec: float) -> bool:
    if timeout_sec <= 0:
        return True
    start = time.time()
    while time.time() - start < timeout_sec:
        ret, _ = cap.read()
        if ret:
            return True
        time.sleep(0.05)
    return False


def open_cameras(
    indices: List[int],
    fps: float,
    width: int,
    height: int,
    target_count: int = 0,
    probe_sec: float = 0.0,
) -> Dict[int, cv2.VideoCapture]:
    caps: Dict[int, cv2.VideoCapture] = {}
    for idx in indices:
        if target_count and len(caps) >= target_count:
            break
        cap, backend_name = _open_camera(idx, fps, width, height)
        if cap is None:
            print(f"Index {idx}: not available or failed to read")
            continue
        if not _probe_camera(cap, probe_sec):
            print(f"Index {idx}: opened but no frames during probe; skipping")
            cap.release()
            continue

        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(
            f"Index {idx}: opened via {backend_name} "
            f"(requested {fps} FPS, reported {actual_fps} FPS, "
            f"{actual_w}x{actual_h})"
        )
        caps[idx] = cap
        time.sleep(OPEN_DELAY_SEC)

    return caps


def _parse_indices(text: str) -> List[int]:
    items = []
    for part in text.split(","):
        part = part.strip()
        if part:
            items.append(int(part))
    return items


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Display multiple cameras at target FPS.")
    parser.add_argument(
        "--indices",
        default=",".join(str(i) for i in DEFAULT_INDICES),
        help="Comma-separated camera indices (default: 0,1,2,3,4,5)",
    )
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS, help="Target FPS")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="Target width")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="Target height")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-scan indices 0..scan-max and keep only cameras that deliver frames",
    )
    parser.add_argument(
        "--scan-max",
        type=int,
        default=DEFAULT_SCAN_MAX,
        help="Max index to scan when --auto is set",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=0,
        help="When --auto is set, stop after this many working cameras",
    )
    parser.add_argument(
        "--probe-sec",
        type=float,
        default=0.0,
        help="Seconds to probe for a valid frame before accepting a camera",
    )
    parser.add_argument(
        "--no-avf-config",
        action="store_true",
        help="Skip AVFoundation FPS configuration on macOS",
    )
    return parser.parse_args()

class CameraState:
    def __init__(self) -> None:
        self.frame: Optional[np.ndarray] = None
        self.last_ts: float = 0.0
        self.fail_count: int = 0
        self.running: bool = True
        self.lock = threading.Lock()


def _reader_loop(idx: int, cap: cv2.VideoCapture, state: CameraState) -> None:
    while state.running:
        ret, frame = cap.read()
        if ret:
            with state.lock:
                state.frame = frame
                state.last_ts = time.time()
                state.fail_count = 0
        else:
            state.fail_count += 1
            if state.fail_count >= MAX_CONSECUTIVE_FAILS:
                break
            time.sleep(0.02)
    cap.release()


def main() -> None:
    args = _parse_args()
    if args.auto:
        indices = list(range(0, args.scan_max + 1))
    else:
        indices = _parse_indices(args.indices)
    target_fps = float(args.fps)
    width = int(args.width)
    height = int(args.height)
    target_count = int(args.target_count)
    probe_sec = float(args.probe_sec)
    if args.auto and probe_sec <= 0:
        probe_sec = 1.0

    if sys.platform == "darwin" and not args.no_avf_config:
        configure_macos_fps(DEFAULT_UIDS, target_fps)

    caps = open_cameras(indices, target_fps, width, height, target_count, probe_sec)
    if not caps:
        print("No cameras opened. Exiting.")
        return

    states: Dict[int, CameraState] = {i: CameraState() for i in caps}
    threads: Dict[int, threading.Thread] = {}
    for idx, cap in caps.items():
        t = threading.Thread(target=_reader_loop, args=(idx, cap, states[idx]), daemon=True)
        t.start()
        threads[idx] = t

        cv2.namedWindow(f"Camera {idx}", cv2.WINDOW_NORMAL)
        cv2.resizeWindow(f"Camera {idx}", width, height)

    last_times: Dict[int, float] = {i: time.time() for i in caps}
    frame_counts: Dict[int, int] = {i: 0 for i in caps}
    measured_fps: Dict[int, float] = {i: 0.0 for i in caps}

    while True:
        for idx in list(states.keys()):
            state = states[idx]
            if not state.running and state.fail_count >= MAX_CONSECUTIVE_FAILS:
                print(f"Index {idx}: too many read failures; closing", flush=True)
                states.pop(idx, None)
                cv2.destroyWindow(f"Camera {idx}")
                continue

            with state.lock:
                frame = state.frame.copy() if state.frame is not None else None

            if frame is None:
                frame = np.zeros((height, width, 3), dtype=np.uint8)
                cv2.putText(
                    frame,
                    f"Index {idx}: NO FRAME",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                    cv2.LINE_AA,
                )
            else:
                frame_counts[idx] += 1
                now = time.time()
                elapsed = now - last_times[idx]
                if elapsed >= 1.0:
                    measured_fps[idx] = frame_counts[idx] / elapsed
                    frame_counts[idx] = 0
                    last_times[idx] = now

            label = f"Index {idx} | target {target_fps:.0f} FPS | measured {measured_fps[idx]:.1f} FPS"
            cv2.putText(
                frame,
                label,
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

            cv2.imshow(f"Camera {idx}", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
        if not states:
            break
        time.sleep(0.01)

    for state in states.values():
        state.running = False
    for t in threads.values():
        t.join(timeout=1.0)
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

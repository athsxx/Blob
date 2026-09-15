"""
Camera Worker Module

Handles individual camera capture in a separate process.
Loads ROIs from per-camera config files and outputs standardized
detection results via IPC queue.

Features:
- Auto-reconnect on camera disconnect
- Health status monitoring
- Standardized JSON output contract
"""

import cv2
import numpy as np
import os
import json
import time
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# HSV detection settings for green laser
GREEN_LASER_SETTINGS = {
    'hue_min': 35,
    'hue_max': 85,
    'sat_min': 40,
    'val_min': 80,
    'pixel_thresh': 8,
    'intensity_thresh': 120,
    'dominance_ratio': 1.3,
}

# Only treat a buffer as dead if it is essentially all zeros (USB underrun).
# Dim metal in workshop light often has mean < 8 and must still be shown.
_DEAD_FRAME_MAX = 1.5


def _fourcc_name(value: float) -> str:
    try:
        v = int(value)
        chars = "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4))
        if all(32 <= ord(c) < 127 for c in chars):
            return chars
        return f"0x{v:08x}"
    except Exception:
        return "?"


def _frame_quality(frame: Optional[np.ndarray]) -> Tuple[str, Dict[str, float]]:
    """Classify a buffer: ok / dead_* / corrupt_*. Stats are for logs."""
    stats: Dict[str, float] = {
        "mean": -1.0,
        "max": -1.0,
        "val_mean": -1.0,
        "neon": -1.0,
        "chroma_rows": -1.0,
        "w": 0.0,
        "h": 0.0,
    }
    if frame is None or getattr(frame, "size", 0) == 0:
        return "dead_empty", stats
    try:
        stats["h"] = float(frame.shape[0])
        stats["w"] = float(frame.shape[1])
        stats["max"] = float(np.max(frame))
        stats["mean"] = float(np.mean(frame))
        if stats["max"] < _DEAD_FRAME_MAX:
            return "dead_black", stats
        small = cv2.resize(frame, (80, 60), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]
        stats["val_mean"] = float(val.mean())
        stats["neon"] = float(((sat > 160) & (val > 30)).mean())
        g = small[:, :, 1].astype(np.int16)
        r = small[:, :, 2].astype(np.int16)
        row_chroma = np.abs(g - r).mean(axis=1)
        stats["chroma_rows"] = float((row_chroma > 45).mean())
        if stats["val_mean"] < 40.0 and stats["neon"] > 0.025:
            return "corrupt_neon_dark", stats
        if stats["neon"] > 0.12:
            return "corrupt_neon", stats
        if stats["chroma_rows"] > 0.30:
            return "corrupt_chroma_stripes", stats
        return "ok", stats
    except Exception as exc:
        stats["error"] = -1.0
        return f"quality_error:{exc}", stats


def _frame_is_dead(frame: Optional[np.ndarray]) -> bool:
    reason, _ = _frame_quality(frame)
    return reason.startswith("dead_")


def _frame_is_corrupt(frame: Optional[np.ndarray]) -> bool:
    reason, _ = _frame_quality(frame)
    return reason.startswith("corrupt_")


def _fmt_stats(stats: Dict[str, float]) -> str:
    return (
        f"mean={stats.get('mean', -1):.1f} val={stats.get('val_mean', -1):.1f} "
        f"max={stats.get('max', -1):.0f} neon={stats.get('neon', -1):.3f} "
        f"chroma={stats.get('chroma_rows', -1):.3f} "
        f"{int(stats.get('w', 0))}x{int(stats.get('h', 0))}"
    )


class _CamTrace:
    """Per-face diagnostic log: console + logs/camera_face_X.log (flushed)."""

    def __init__(self, face: str, log_dir: str):
        self.face = face
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, f"camera_face_{face}.log")
        self._fp = open(self.path, "a", encoding="utf-8")
        self.n: Dict[str, int] = defaultdict(int)
        self.emit(f"=== trace open file={self.path} pid={os.getpid()} ===")

    def emit(self, msg: str) -> None:
        line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} [CAM_{self.face}] {msg}"
        print(line, flush=True)
        try:
            self._fp.write(line + "\n")
            self._fp.flush()
        except Exception:
            pass

    def bump(self, key: str) -> int:
        self.n[key] += 1
        return self.n[key]

    def maybe(self, key: str, msg: str, first: int = 3, every: int = 25) -> int:
        n = self.bump(key)
        if n <= first or n % every == 0:
            self.emit(f"{msg} (count={n})")
        return n

    def close(self) -> None:
        try:
            self.emit("=== trace close ===")
            self._fp.close()
        except Exception:
            pass


class CameraWorker:
    """
    Manages a single camera's capture and detection loop.
    Designed to run in a separate process.
    """
    
    def __init__(self, usb_index: int, face: str, config_file: str,
                 result_queue, control_event, display_queue=None,
                 capture_settings: Optional[Dict[str, Any]] = None,
                 hub_id: Optional[int] = None,
                 open_semaphore=None,
                 command_queue=None,
                 ready_queue=None):
        """
        Args:
            usb_index: USB camera index (0-5)
            face: Manifold face this camera views (A-F)
            config_file: Path to hole positions JSON
            result_queue: Multiprocessing queue for detection results
            control_event: Event to signal shutdown
            display_queue: Optional queue for frames to display
        """
        self.usb_index = usb_index
        self.face = face
        self.config_file = config_file
        self.result_queue = result_queue
        self.control_event = control_event
        self.display_queue = display_queue
        self.capture_settings = capture_settings or {}
        self.hub_id = hub_id
        self.open_semaphore = open_semaphore
        self.command_queue = command_queue
        self.ready_queue = ready_queue
        log_dir = str(self.capture_settings.get("log_dir") or "")
        if not log_dir:
            log_dir = os.path.abspath(os.path.join(os.path.dirname(self.config_file), "..", "..", "logs"))
        self.trace = _CamTrace(self.face, log_dir)
        self.trace.emit(
            f"worker init usb={self.usb_index} hub={self.hub_id} "
            f"target_fps={self.capture_settings.get('target_fps')} "
            f"config={self.config_file}"
        )
        
        # State
        self.cap = None
        self.rois = []
        self.target_hole_id = None  # Hole ID to highlight as next target
        self.is_connected = False
        self.reconnect_attempts = 0
        self._gave_up = False
        self._ready_emitted = False
        # Robust mode settings
        self.robust_mode = bool(self.capture_settings.get("robust_mode", False))
        self.max_read_retries = int(self.capture_settings.get("max_read_retries", 3))
        self.max_reconnect_attempts = int(self.capture_settings.get("max_reconnect_attempts", 8))
        self.min_width = int(self.capture_settings.get("min_width", 0))
        self.reconnect_backoff_s = float(self.capture_settings.get("reconnect_cooldown", 1.0))
        self.reconnect_backoff_initial = self.reconnect_backoff_s
        self.reconnect_backoff_max_s = 10.0
        # Frame throttling settings
        self.target_fps = float(self.capture_settings.get("target_fps", 15))
        self.reject_high_res = bool(self.capture_settings.get("reject_high_res", False))
        self.reject_high_fps = bool(self.capture_settings.get("reject_high_fps", False))
        self.frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        self.last_process_time = 0
        self.display_fps = float(self.capture_settings.get("display_fps", self.target_fps or 5))
        self.display_interval = 1.0 / self.display_fps if self.display_fps > 0 else 0
        self.last_display_time = 0
        self._roi_scale = (1.0, 1.0)
        self._roi_calib = (
            int(self.capture_settings.get("roi_calib_width", 640)),
            int(self.capture_settings.get("roi_calib_height", 480)),
        )
        # Detection settings
        self.detection_settings = dict(GREEN_LASER_SETTINGS)
        # Pre-computed HSV bounds (set once, reuse every frame)
        s = self.detection_settings
        self._lower_green = np.array([s['hue_min'], s['sat_min'], s['val_min']])
        self._upper_green = np.array([s['hue_max'], 255, 255])
        
        # Pre-computed ROI masks (built after first frame size is known)
        self.roi_masks: Dict[str, np.ndarray] = {}
        self.roi_mask_bools: Dict[str, np.ndarray] = {}  # boolean version
        self._masks_built = False
        self._frame_size: Optional[Tuple[int, int]] = None  # (h, w)
        
        # Display frame size (send compressed frames to reduce IPC overhead)
        self.display_size = (
            int(self.capture_settings.get("display_width", 480)),
            int(self.capture_settings.get("display_height", 360)),
        )
        self.last_detections = []  # Store last detections for display overlay
        
        # Health metrics
        self.frame_count = 0
        self.last_frame_time = 0
        self.fps_actual = 0
        self._last_good: Optional[np.ndarray] = None
        self._gave_up_at = 0.0
        
        # Detection history for temporal stability
        self.detection_history: Dict[str, List[bool]] = {}
        self.min_stable_frames = 3
    
    def load_rois(self) -> bool:
        """Load ROI definitions from config file."""
        if not os.path.exists(self.config_file):
            self.trace.emit(f"Warning: Config not found: {self.config_file}")
            return False
        
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            
            raw_circles = data.get('circles', [])
            self.rois = []
            
            for i, c in enumerate(raw_circles):
                if isinstance(c, list):
                    # Old format: [cx, cy, r]
                    name = f"H{i+1}"
                    cx, cy, r = c
                    w, h, angle = r, r, 0
                elif isinstance(c, dict):
                    # New format: {'name': 'A1', 'coords': [cx, cy, r], 'w': .., 'h': .., 'angle': ..}
                    name = c.get('name', f"H{i+1}")
                    cx, cy, r = c['coords']
                    w = c.get('w', r)
                    h = c.get('h', r)
                    angle = c.get('angle', 0)
                else:
                    continue
                
                self.rois.append({
                    'roi_id': f"{self.face}_{name}",
                    'hole_id': name,
                    'cx': cx,
                    'cy': cy,
                    'radius': r,
                    'w': w,
                    'h': h,
                    'angle': angle
                })
                
                # Initialize detection history
                self.detection_history[name] = []
            
            self.trace.emit(f"Loaded {len(self.rois)} ROIs from {self.config_file}")
            self._masks_built = False  # Force mask rebuild on next frame
            return True
            
        except Exception as e:
            self.trace.emit(f"Error loading config: {e}")
            return False

    def _scaled_roi(self, roi: Dict[str, Any]) -> Tuple[int, int, int, int, float]:
        sx, sy = self._roi_scale
        cx = int(round(roi["cx"] * sx))
        cy = int(round(roi["cy"] * sy))
        w = max(1, int(round(roi.get("w", roi.get("radius", 20)) * sx)))
        h = max(1, int(round(roi.get("h", roi.get("radius", 20)) * sy)))
        return cx, cy, w, h, float(roi.get("angle", 0))

    def _build_roi_masks(self, frame_h: int, frame_w: int):
        """Pre-compute ROI masks once when frame size is known. Scale from 640×480 calibration."""
        self.roi_masks = {}
        self.roi_mask_bools = {}
        self._frame_size = (frame_h, frame_w)
        calib_w, calib_h = self._roi_calib
        self._roi_scale = (
            frame_w / float(calib_w or frame_w),
            frame_h / float(calib_h or frame_h),
        )

        for roi in self.rois:
            hole_id = roi['hole_id']
            cx, cy, roi_w, roi_h, angle = self._scaled_roi(roi)
            radius = max(roi_w, roi_h)

            mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
            if roi_w == roi_h:
                cv2.circle(mask, (cx, cy), radius, 255, -1)
            else:
                cv2.ellipse(mask, (cx, cy), (roi_w, roi_h), angle, 0, 360, 255, -1)

            self.roi_masks[hole_id] = mask
            self.roi_mask_bools[hole_id] = mask > 0

        self._masks_built = True
        self.trace.emit(
            f"Built {len(self.roi_masks)} ROI masks "
            f"({frame_w}x{frame_h}, scale {self._roi_scale[0]:.2f}x{self._roi_scale[1]:.2f})"
        )

    def detect_green_laser_in_roi(self, green_mask, b_ch, g_ch, r_ch, roi):
        """
        Detect green laser in an ROI using pre-computed mask and pre-split channels.
        
        Args:
            green_mask: Pre-computed HSV green mask for the entire frame
            b_ch, g_ch, r_ch: Pre-split BGR channels (computed once per frame)
            roi: ROI dict with hole_id key
        Returns:
            (detected: bool, confidence: float, pixel_count: int, max_intensity: float)
        """
        hole_id = roi['hole_id']
        mask = self.roi_masks.get(hole_id)
        mask_bool = self.roi_mask_bools.get(hole_id)
        
        if mask is None or mask_bool is None:
            return False, 0.0, 0, 0.0
        
        if not np.any(mask_bool):
            return False, 0.0, 0, 0.0
        
        settings = self.detection_settings
        
        # HSV green pixel count within this ROI
        green_in_roi = cv2.bitwise_and(green_mask, mask)
        pixel_count = cv2.countNonZero(green_in_roi)
        
        # RGB dominance check using pre-split channels
        g_val = g_ch[mask_bool].astype(float)
        r_val = r_ch[mask_bool].astype(float)
        b_val = b_ch[mask_bool].astype(float)
        
        max_green = float(np.max(g_val)) if len(g_val) > 0 else 0.0
        
        dominance_ratio = 0.0
        if max_green > 0:
            max_idx = np.argmax(g_val)
            rb_avg = (r_val[max_idx] + b_val[max_idx]) / 2.0
            if rb_avg < 1:
                rb_avg = 1
            dominance_ratio = max_green / rb_avg
        
        has_any_green = pixel_count >= 1
        has_bright_green = max_green >= 150
        has_green_dominant = dominance_ratio >= 1.2
        detected = has_any_green and (has_bright_green or has_green_dominant)
        
        pixel_score = min(1.0, pixel_count / (settings['pixel_thresh'] * 3))
        intensity_score = min(1.0, max_green / 255.0)
        dominance_score = min(1.0, dominance_ratio / (settings['dominance_ratio'] * 2))
        confidence = (pixel_score * 0.3 + intensity_score * 0.4 + dominance_score * 0.3)
        if not detected:
            confidence = min(confidence, 0.49)
        
        return detected, round(confidence, 3), pixel_count, round(max_green, 1)
    
    def connect(self) -> bool:
        """Attempt to connect to the camera."""
        try:
            backend_name = str(self.capture_settings.get("backend", "auto")).lower().strip()
            allow_fallback = bool(self.capture_settings.get("allow_backend_fallback", True))
            if backend_name in {"auto", "default", ""}:
                if sys.platform == "darwin":
                    backend_candidates = [("avfoundation", cv2.CAP_AVFOUNDATION), ("any", cv2.CAP_ANY)]
                elif sys.platform == "win32":
                    # Prefer DirectShow so indices match camera_indexer / CAP_DSHOW.
                    backend_candidates = [("dshow", cv2.CAP_DSHOW), ("msmf", cv2.CAP_MSMF), ("any", cv2.CAP_ANY)]
                else:
                    backend_candidates = [("v4l2", cv2.CAP_V4L2), ("any", cv2.CAP_ANY)]
            elif backend_name in {"avfoundation", "avf"}:
                # Try AVFoundation first; fall back to CAP_ANY if index 0 fails (e.g. no device, or in use)
                backend_candidates = [("avfoundation", cv2.CAP_AVFOUNDATION), ("any", cv2.CAP_ANY)]
            elif backend_name == "ffmpeg":
                backend_candidates = [("ffmpeg", cv2.CAP_FFMPEG)]
            elif backend_name == "msmf":
                backend_candidates = [("msmf", cv2.CAP_MSMF)]
                if allow_fallback and sys.platform == "win32":
                    backend_candidates += [("dshow", cv2.CAP_DSHOW), ("any", cv2.CAP_ANY)]
            elif backend_name == "dshow":
                backend_candidates = [("dshow", cv2.CAP_DSHOW)]
                if allow_fallback and sys.platform == "win32":
                    # MSMF as last resort only — index order can differ from DSHOW.
                    backend_candidates += [("msmf", cv2.CAP_MSMF), ("any", cv2.CAP_ANY)]
            elif backend_name == "v4l2":
                backend_candidates = [("v4l2", cv2.CAP_V4L2)]
            else:
                backend_candidates = [("any", cv2.CAP_ANY)]

            used_backend_name = None
            used_fourcc = None
            if self.open_semaphore is not None:
                self.open_semaphore.acquire()
            try:
                presets = self.capture_settings.get("presets")
                if not presets:
                    presets = [self.capture_settings]
                warmup_reads = int(self.capture_settings.get("warmup_reads", 1))
                settle_s = float(self.capture_settings.get("open_settle_s", 1.0))

                self.cap = None
                # Use stable device_path if set (e.g. /dev/v4l/by-path/... on Linux), else usb_index
                open_target = self.capture_settings.get("device_path") or self.usb_index
                for preset in presets:
                    for name, backend in backend_candidates:
                        width = preset.get("width")
                        height = preset.get("height")
                        fps = preset.get("fps")
                        fourcc = preset.get("fourcc")
                        self.trace.emit(
                            f"try open target={open_target} backend={name} "
                            f"want={width}x{height}@{fps} fourcc={fourcc or 'native'}"
                        )
                        cap = cv2.VideoCapture(open_target, backend)
                        if not cap.isOpened():
                            self.trace.emit(f"open FAILED isOpened=false backend={name} target={open_target}")
                            cap.release()
                            continue

                        # Apply preset properties. On Windows DirectShow, set FOURCC
                        # before width/height so the driver renegotiates once onto a
                        # bandwidth-friendly format (MJPG) instead of default YUY2.
                        if fourcc:
                            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*str(fourcc)))
                        if width:
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
                        if height:
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
                        if fps:
                            cap.set(cv2.CAP_PROP_FPS, float(fps))
                            cap.set(cv2.CAP_PROP_FPS, float(fps))

                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = cap.get(cv2.CAP_PROP_FPS)
                        self.trace.emit(
                            f"negotiated {actual_w}x{actual_h} fps={actual_fps:.2f} "
                            f"fourcc={_fourcc_name(cap.get(cv2.CAP_PROP_FOURCC))} "
                            f"buf={int(cap.get(cv2.CAP_PROP_BUFFERSIZE))}"
                        )

                        live = None
                        saw_zero_buffer = False
                        warmup_ok = 0
                        warmup_fail = 0
                        last_q = "none"
                        last_stats: Dict[str, float] = {}
                        for _ in range(max(1, warmup_reads)):
                            ok, frame = cap.read()
                            if not ok or frame is None:
                                warmup_fail += 1
                                time.sleep(0.08)
                                continue
                            last_q, last_stats = _frame_quality(frame)
                            if last_q.startswith("dead_"):
                                saw_zero_buffer = True
                                warmup_fail += 1
                                time.sleep(0.05)
                                continue
                            warmup_ok += 1
                            live = frame
                            break
                        if live is None:
                            reason = "all-zero buffers" if saw_zero_buffer else "no frames"
                            self.trace.emit(
                                f"warmup FAIL ({reason}) reads_ok={warmup_ok} reads_fail={warmup_fail} "
                                f"last={last_q} {_fmt_stats(last_stats)} — next format"
                            )
                            cap.release()
                            continue
                        self.trace.emit(
                            f"warmup OK after {warmup_ok + warmup_fail} reads "
                            f"last={last_q} {_fmt_stats(last_stats)}"
                        )

                        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = cap.get(cv2.CAP_PROP_FPS)

                        if self.min_width and actual_w and actual_w < self.min_width:
                            self.trace.emit(
                                f"Rejecting {actual_w}x{actual_h} (need width ≥ {self.min_width})"
                            )
                            cap.release()
                            continue

                        # Reject cameras that stay at high resolution (USB bandwidth issue)
                        if self.reject_high_res and actual_w > 640:
                            self.trace.emit(f"Rejecting {actual_w}x{actual_h} - resolution too high (need ≤640)")
                            cap.release()
                            continue

                        # Reject cameras that report excessively high FPS
                        if self.reject_high_fps and actual_fps > 30:
                            self.trace.emit(f"Rejecting @ {actual_fps}fps - FPS too high (need ≤30)")
                            cap.release()
                            continue

                        self.cap = cap
                        used_backend_name = name
                        used_fourcc = fourcc
                        self._used_backend_name = name
                        break
                    if self.cap is not None and self.cap.isOpened():
                        break

                # Settle delay — let the USB stack fully establish the connection
                # before the next camera tries to open on the same hub.
                if self.cap is not None and self.cap.isOpened() and settle_s > 0:
                    time.sleep(settle_s)
            finally:
                if self.open_semaphore is not None:
                    self.open_semaphore.release()
            
            if self.cap is not None and self.cap.isOpened():
                self.is_connected = True
                self.reconnect_attempts = 0
                self.reconnect_backoff_s = 0.5
                if self.target_fps > 0:
                    self.cap.set(cv2.CAP_PROP_FPS, float(self.target_fps))
                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                open_desc = self.capture_settings.get("device_path") or f"USB {self.usb_index}"
                reported_fourcc = _fourcc_name(self.cap.get(cv2.CAP_PROP_FOURCC))
                self.trace.emit(
                    f"CONNECTED {open_desc} {actual_w}x{actual_h} "
                    f"reported_fps={actual_fps:.2f} backend={used_backend_name or backend_name} "
                    f"req_fourcc={used_fourcc or 'native'} got_fourcc={reported_fourcc}"
                )
                return True
            else:
                open_desc = self.capture_settings.get("device_path") or f"USB index {self.usb_index}"
                tried = ",".join(n for n, _ in backend_candidates)
                self.trace.emit(
                    f"FAILED open {open_desc} requested={backend_name} tried={tried}"
                )
                return False
                
        except Exception as e:
            self.trace.emit(f"Connection error: {e}")
            if self.cap is not None:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            return False
    
    def reconnect(self) -> bool:
        """Attempt to reconnect after disconnect."""
        self.reconnect_attempts += 1
        self.trace.emit(
            f"reconnect attempt {self.reconnect_attempts} backoff={self.reconnect_backoff_s:.1f}s"
        )
        
        # Release old capture and wait for OS to fully release device
        if self.cap:
            self.cap.release()
            self.cap = None
            # Extra delay to ensure OS releases the camera device
            time.sleep(0.3)
        
        time.sleep(self.reconnect_backoff_s)
        success = self.connect()
        if not success:
            self.reconnect_backoff_s = min(
                self.reconnect_backoff_s * 1.5,
                self.reconnect_backoff_max_s
            )
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                self._gave_up = True
                self._gave_up_at = time.time()
                self.trace.emit(
                    f"giving up after {self.reconnect_attempts} failed opens; retry in 45s"
                )
        else:
            # Reset backoff on success
            self.reconnect_backoff_s = self.reconnect_backoff_initial
            self._gave_up = False
        return success
    
    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Process a single frame and detect lasers in all ROIs.
        Uses HSV color-based green laser detection.
        
        Optimizations:
        - Pre-computed ROI masks (built once on first frame)
        - Batch HSV conversion and channel splitting (once per frame)
        - Pre-computed HSV bounds
        
        Returns:
            Detection result dict matching PRD contract
        """
        timestamp = datetime.now()
        h, w = frame.shape[:2]
        
        # Build ROI masks on first frame (or if frame size changes)
        if not self._masks_built or self._frame_size != (h, w):
            self._build_roi_masks(h, w)
        
        # --- Batch operations: computed ONCE per frame, not per ROI ---
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        green_mask = cv2.inRange(hsv_frame, self._lower_green, self._upper_green)
        b_ch, g_ch, r_ch = cv2.split(frame)
        
        detections = []
        
        for roi in self.rois:
            hole_id = roi['hole_id']
            
            # Detect using pre-split channels and pre-computed masks
            detected, confidence, pixels, intensity = self.detect_green_laser_in_roi(
                green_mask, b_ch, g_ch, r_ch, roi
            )
            
            # Update detection history for temporal stability
            history = self.detection_history.get(hole_id, [])
            history.append(detected)
            if len(history) > self.min_stable_frames:
                history = history[-self.min_stable_frames:]
            self.detection_history[hole_id] = history
            
            # Check stability: laser must be detected for N consecutive frames
            stable_detection = len(history) >= self.min_stable_frames and all(history)
            stable_frames = sum(history)
            
            detections.append({
                'roi_id': roi['roi_id'],
                'hole_id': hole_id,
                'laser': stable_detection,
                'raw_detection': detected,
                'confidence': confidence,
                'stable_frames': stable_frames,
                'intensity': intensity,
                'pixels': pixels
            })
        
        # Build output contract
        result = {
            'camera_id': f"CAM_{self.face}",
            'face': self.face,
            'usb_index': self.usb_index,
            'timestamp': timestamp.isoformat(),
            'timestamp_epoch': timestamp.timestamp(),
            'detections': detections,
            'health': {
                'connected': self.is_connected,
                'fps': self.fps_actual,
                'frame_count': self.frame_count
            }
        }
        
        return result
    
    def draw_overlays(self, frame: np.ndarray, detections: List[Dict]) -> np.ndarray:
        """Draw ROI ellipses/circles and detection status on frame."""
        display = frame.copy()
        
        # Map detections by hole_id for O(1) lookup
        det_map = {d['hole_id']: d for d in detections}
        
        for roi in self.rois:
            hole_id = roi['hole_id']
            cx, cy, w, h, angle = self._scaled_roi(roi)
            
            is_target = (self.target_hole_id == hole_id)
            
            # Determine status/color
            det = det_map.get(hole_id)
            if det:
                if det['laser']:
                    color = (0, 255, 0)  # Green - stable detection
                elif det['raw_detection']:
                    color = (0, 255, 255)  # Yellow - detected but unstable
                elif is_target:
                    color = (0, 255, 255)  # Yellow - active target
                else:
                    color = (0, 0, 255)  # Red - processed but no laser
            else:
                if is_target:
                    color = (0, 255, 255)  # Yellow - active target
                else:
                    color = (128, 128, 128)  # Gray - no detection info yet
            
            thickness = 2
            
            # Target hole: draw prominent indicator
            if is_target:
                thickness = 3
                # Outer pulsing ring (larger)
                pulse_r = int(max(w, h) * 1.4)
                cv2.circle(display, (cx, cy), pulse_r, (0, 255, 255), 1)
            
            # Draw shape
            if w == h:
                cv2.circle(display, (cx, cy), w, color, thickness)
            else:
                cv2.ellipse(display, (cx, cy), (w, h), angle, 0, 360, color, thickness)
            
            # Draw label
            label = f"{hole_id}"
            if det and det['laser']:
                label += " OK"
            cv2.putText(display, label, (cx - 20, cy - max(w, h) - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # Draw camera info
        info = f"CAM_{self.face} | FPS: {self.fps_actual:.1f} | Frame: {self.frame_count}"
        cv2.putText(display, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        # Draw target indicator banner if this camera has the active target
        if self.target_hole_id:
            target_text = f"TARGET: {self.target_hole_id}"
            h_frame = display.shape[0]
            cv2.putText(display, target_text, (10, h_frame - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        
        return display
    
    def run(self):
        """Main capture loop. Call this in a separate process."""
        self.trace.emit(f"Starting worker...")
        
        # Load ROIs
        self.load_rois()
        
        # Initial connection
        ok = self.connect()
        if not ok:
            self.trace.emit(f"Initial connection failed. Will retry...")
        self._emit_ready(ok)
        
        last_fps_time = time.time()
        fps_frame_count = 0
        next_use = 0.0
        fail_streak = 0
        corrupt_streak = 0
        hold_since = None
        holding = False
        last_heartbeat = time.time()
        last_quality = "ok"
        last_stats: Dict[str, float] = {}
        t0 = time.time()
        
        while not self.control_event.is_set():
            # Check connection
            if not self.is_connected:
                if self._gave_up:
                    if time.time() - self._gave_up_at > 45.0:
                        self.trace.emit("Cooldown over — retrying camera open")
                        self._gave_up = False
                        self.reconnect_attempts = 0
                    else:
                        time.sleep(1)
                        continue
                if not self.reconnect():
                    time.sleep(1)
                    continue

            # Always dequeue a USB sample. Sleeping between reads lets DirectShow
            # stall after a few minutes and the tile looks frozen.
            try:
                grabbed = bool(self.cap is not None and self.cap.grab())
            except Exception as exc:
                grabbed = False
                self.trace.maybe("grab_exc", f"grab exception: {exc!r}", first=5, every=50)
            if not grabbed:
                fail_streak += 1
                self.trace.maybe(
                    "grab_fail",
                    f"grab FAIL streak={fail_streak} cap={self.cap is not None}",
                    first=5,
                    every=25,
                )
                if fail_streak >= 25:
                    self.trace.emit("DirectShow grab stalled — reconnecting")
                    self.is_connected = False
                    fail_streak = 0
                    if self.cap:
                        self.cap.release()
                        self.cap = None
                else:
                    time.sleep(0.01)
                continue
            self.trace.bump("grab_ok")

            now = time.time()
            if self.frame_interval > 0 and now < next_use:
                time.sleep(0.001)
                continue
            next_use = now + (self.frame_interval if self.frame_interval > 0 else 0.2)

            try:
                ok, frame = self.cap.retrieve()
            except Exception as exc:
                ok, frame = False, None
                self.trace.maybe("retrieve_exc", f"retrieve exception: {exc!r}", first=5, every=50)
            if not ok or frame is None:
                fail_streak += 1
                self.trace.maybe(
                    "retrieve_fail",
                    f"retrieve FAIL streak={fail_streak}",
                    first=5,
                    every=25,
                )
                if fail_streak >= 25:
                    self.trace.emit("Frame retrieve stalled — reconnecting")
                    self.is_connected = False
                    fail_streak = 0
                    if self.cap:
                        self.cap.release()
                        self.cap = None
                continue
            fail_streak = 0
            self.trace.bump("retrieve_ok")

            # Color-space safety: ensure frame is 3-channel BGR
            if len(frame.shape) == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            last_quality, last_stats = _frame_quality(frame)
            if last_quality != "ok":
                self.trace.bump(last_quality)
                self.trace.maybe(
                    f"q_{last_quality}",
                    f"BAD frame {last_quality} {_fmt_stats(last_stats)}",
                    first=5,
                    every=20,
                )

            # Short hold on neon USB garbage, then force a refresh so tiles cannot
            # freeze on last-good for minutes.
            live_bad = last_quality != "ok"
            if live_bad:
                corrupt_streak += 1
                if self._last_good is not None and corrupt_streak >= 3:
                    if hold_since is None:
                        hold_since = now
                        holding = True
                        self.trace.emit(
                            f"HOLD last-good start reason={last_quality} {_fmt_stats(last_stats)}"
                        )
                    if now - hold_since < 1.5:
                        frame = self._last_good
                        self.trace.bump("hold_frames")
                    else:
                        self.trace.emit(
                            f"HOLD expired — forcing live frame reason={last_quality} {_fmt_stats(last_stats)}"
                        )
                        hold_since = None
                        holding = False
                        corrupt_streak = 0
                        self._last_good = frame.copy()
                        self.trace.bump("hold_refresh")
                elif self._last_good is None:
                    self.trace.bump("drop_no_last_good")
                    continue
            else:
                if holding:
                    self.trace.emit(f"HOLD end — live OK {_fmt_stats(last_stats)}")
                corrupt_streak = 0
                hold_since = None
                holding = False
                self._last_good = frame.copy()
            
            self.frame_count += 1
            fps_frame_count += 1
            
            now = time.time()
            if now - last_fps_time >= 1.0:
                self.fps_actual = fps_frame_count / (now - last_fps_time)
                fps_frame_count = 0
                last_fps_time = now
            if now - last_heartbeat >= 10.0:
                laser_n = sum(1 for d in self.last_detections if d.get("laser"))
                self.trace.emit(
                    f"HEARTBEAT uptime={now - t0:.0f}s fps={self.fps_actual:.2f} "
                    f"used_frames={self.frame_count} grab_ok={self.trace.n['grab_ok']} "
                    f"grab_fail={self.trace.n['grab_fail']} retrieve_ok={self.trace.n['retrieve_ok']} "
                    f"retrieve_fail={self.trace.n['retrieve_fail']} "
                    f"dead_black={self.trace.n['dead_black']} "
                    f"corrupt_neon_dark={self.trace.n['corrupt_neon_dark']} "
                    f"corrupt_neon={self.trace.n['corrupt_neon']} "
                    f"hold_frames={self.trace.n['hold_frames']} "
                    f"hold_refresh={self.trace.n['hold_refresh']} "
                    f"display_drop={self.trace.n['display_drop']} "
                    f"result_drop={self.trace.n['result_drop']} "
                    f"holding={holding} last_q={last_quality} {_fmt_stats(last_stats)} "
                    f"lasers={laser_n}"
                )
                last_heartbeat = now
            
            if self.command_queue:
                try:
                    cmd = self.command_queue.get_nowait()
                    if cmd.get('action') == 'set_target':
                        self.target_hole_id = cmd.get('hole_id')
                        self.trace.emit(f"command set_target hole={self.target_hole_id}")
                except Exception:
                    pass

            if self.display_queue:
                try:
                    fh, fw = frame.shape[:2]
                    if not self._masks_built or self._frame_size != (fh, fw):
                        self._build_roi_masks(fh, fw)
                    display_frame = self.draw_overlays(frame, self.last_detections)
                    dw, dh = self.display_size
                    if display_frame.shape[1] > dw or display_frame.shape[0] > dh:
                        small = cv2.resize(display_frame, (dw, dh))
                    else:
                        small = display_frame
                    self.display_queue.put_nowait((f"CAM_{self.face}", small))
                    self.last_display_time = now
                except Exception as exc:
                    self.trace.maybe("display_drop", f"display queue drop: {exc!r}", first=3, every=50)
            
            t_proc = time.time()
            result = self.process_frame(frame)
            proc_ms = (time.time() - t_proc) * 1000.0
            if proc_ms > 80:
                self.trace.maybe("slow_proc", f"process_frame slow {proc_ms:.0f}ms", first=3, every=20)
            self.last_detections = result['detections']
            try:
                self.result_queue.put_nowait(result)
            except Exception as exc:
                self.trace.maybe("result_drop", f"result queue drop: {exc!r}", first=3, every=50)
        
        # Cleanup
        if self.cap:
            self.cap.release()
            self.cap = None
        self.trace.emit("Worker stopped.")
        self.trace.close()

    def _emit_ready(self, ok: bool) -> None:
        if self._ready_emitted or self.ready_queue is None:
            return
        self._ready_emitted = True
        width = height = 0
        if self.cap is not None:
            try:
                width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            except Exception:
                pass
        try:
            self.ready_queue.put({
                "face": self.face,
                "ok": bool(ok),
                "usb_index": self.usb_index,
                "width": width,
                "height": height,
                "backend": getattr(self, "_used_backend_name", "") or "",
            })
        except Exception:
            pass


def camera_worker_process(usb_index: int, face: str, config_file: str,
                          result_queue, control_event, display_queue=None,
                          capture_settings: Optional[Dict[str, Any]] = None,
                          hub_id: Optional[int] = None,
                          open_semaphore=None,
                          command_queue=None,
                          ready_queue=None):
    """
    Entry point for multiprocessing.Process target.
    """
    worker = CameraWorker(
        usb_index=usb_index,
        face=face,
        config_file=config_file,
        result_queue=result_queue,
        control_event=control_event,
        display_queue=display_queue,
        capture_settings=capture_settings,
        hub_id=hub_id,
        open_semaphore=open_semaphore,
        command_queue=command_queue,
        ready_queue=ready_queue,
    )
    worker.run()

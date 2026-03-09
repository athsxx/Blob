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
                 command_queue=None):
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
        self.hub_id = hub_id
        self.open_semaphore = open_semaphore
        self.command_queue = command_queue
        
        # State
        self.cap = None
        self.rois = []
        self.target_hole_id = None  # Hole ID to highlight as next target
        self.is_connected = False
        self.reconnect_attempts = 0
        # Robust mode settings
        self.robust_mode = bool(self.capture_settings.get("robust_mode", False))
        self.max_read_retries = int(self.capture_settings.get("max_read_retries", 3))
        self.reconnect_backoff_s = float(self.capture_settings.get("reconnect_cooldown", 1.0))
        self.reconnect_backoff_initial = self.reconnect_backoff_s
        self.reconnect_backoff_max_s = 10.0
        # Frame throttling settings
        self.target_fps = float(self.capture_settings.get("target_fps", 15))
        self.reject_high_res = bool(self.capture_settings.get("reject_high_res", False))
        self.reject_high_fps = bool(self.capture_settings.get("reject_high_fps", False))
        self.frame_interval = 1.0 / self.target_fps if self.target_fps > 0 else 0
        self.last_process_time = 0
        # Display throttling - separate from processing throttle
        self.display_fps = 30  # Max 30fps for smooth display without queue overflow
        self.display_interval = 1.0 / self.display_fps
        self.last_display_time = 0
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
        self.display_size = (320, 240)
        self.last_detections = []  # Store last detections for display overlay
        
        # Health metrics
        self.frame_count = 0
        self.last_frame_time = 0
        self.fps_actual = 0
        
        # Detection history for temporal stability
        self.detection_history: Dict[str, List[bool]] = {}
        self.min_stable_frames = 3
    
    def load_rois(self) -> bool:
        """Load ROI definitions from config file."""
        if not os.path.exists(self.config_file):
            print(f"[CAM_{self.face}] Warning: Config not found: {self.config_file}")
            return False
        
        try:
            with open(self.config_file, 'r') as f:
                data = json.load(f)
            
            raw_circles = data.get('circles', [])
            self.rois = []
            
            # Auto-scale ROIs if capture resolution differs from calibration resolution
            cal_res = data.get('calibration_resolution', [640, 480])
            cap_w = int(self.capture_settings.get('width', 640))
            cap_h = int(self.capture_settings.get('height', 480))
            # Use the first preset's resolution if presets exist
            presets = self.capture_settings.get('presets')
            if presets:
                cap_w = int(presets[0].get('width', cap_w))
                cap_h = int(presets[0].get('height', cap_h))
            sx = cap_w / cal_res[0]
            sy = cap_h / cal_res[1]
            needs_scale = abs(sx - 1.0) > 0.01 or abs(sy - 1.0) > 0.01
            if needs_scale:
                print(f"[CAM_{self.face}] Scaling ROIs: calibrated={cal_res[0]}x{cal_res[1]} → capture={cap_w}x{cap_h} (sx={sx:.2f}, sy={sy:.2f})")
            
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
                
                # Apply scale factors if resolution changed
                if needs_scale:
                    cx = int(cx * sx)
                    cy = int(cy * sy)
                    r = max(1, int(r * min(sx, sy)))
                    w = max(1, int(w * sx))
                    h = max(1, int(h * sy))
                
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
            
            print(f"[CAM_{self.face}] Loaded {len(self.rois)} ROIs from {self.config_file}")
            self._masks_built = False  # Force mask rebuild on next frame
            return True
            
        except Exception as e:
            print(f"[CAM_{self.face}] Error loading config: {e}")
            return False

    def _build_roi_masks(self, frame_h: int, frame_w: int):
        """Pre-compute ROI masks once when frame size is known."""
        self.roi_masks = {}
        self.roi_mask_bools = {}
        self._frame_size = (frame_h, frame_w)
        
        for roi in self.rois:
            hole_id = roi['hole_id']
            cx, cy = roi['cx'], roi['cy']
            radius = roi.get('radius', roi.get('w', 40))
            roi_w = roi.get('w', radius)
            roi_h = roi.get('h', radius)
            angle = roi.get('angle', 0)
            
            mask = np.zeros((frame_h, frame_w), dtype=np.uint8)
            if roi_w == roi_h:  # Circle
                cv2.circle(mask, (cx, cy), radius, 255, -1)
            else:  # Ellipse
                cv2.ellipse(mask, (cx, cy), (roi_w, roi_h), angle, 0, 360, 255, -1)
            
            self.roi_masks[hole_id] = mask
            self.roi_mask_bools[hole_id] = mask > 0
        
        self._masks_built = True
        print(f"[CAM_{self.face}] Built {len(self.roi_masks)} pre-computed ROI masks ({frame_w}x{frame_h})")

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
            if backend_name in {"auto", "default", ""}:
                if sys.platform == "darwin":
                    backend_candidates = [("avfoundation", cv2.CAP_AVFOUNDATION), ("any", cv2.CAP_ANY)]
                elif sys.platform == "win32":
                    backend_candidates = [("msmf", cv2.CAP_MSMF), ("dshow", cv2.CAP_DSHOW), ("any", cv2.CAP_ANY)]
                else:
                    backend_candidates = [("v4l2", cv2.CAP_V4L2), ("any", cv2.CAP_ANY)]
            elif backend_name in {"avfoundation", "avf"}:
                # Try AVFoundation first; fall back to CAP_ANY if index 0 fails (e.g. no device, or in use)
                backend_candidates = [("avfoundation", cv2.CAP_AVFOUNDATION), ("any", cv2.CAP_ANY)]
            elif backend_name == "ffmpeg":
                backend_candidates = [("ffmpeg", cv2.CAP_FFMPEG)]
            elif backend_name == "msmf":
                backend_candidates = [("msmf", cv2.CAP_MSMF)]
            elif backend_name == "dshow":
                backend_candidates = [("dshow", cv2.CAP_DSHOW)]
            elif backend_name == "v4l2":
                backend_candidates = [("v4l2", cv2.CAP_V4L2)]
            else:
                backend_candidates = [("any", cv2.CAP_ANY)]

            used_backend_name = None
            if self.open_semaphore is not None:
                self.open_semaphore.acquire()
            try:
                presets = self.capture_settings.get("presets")
                if not presets:
                    presets = [self.capture_settings]
                warmup_reads = int(self.capture_settings.get("warmup_reads", 1))

                self.cap = None
                # Use stable device_path if set (e.g. /dev/v4l/by-path/... on Linux), else usb_index
                open_target = self.capture_settings.get("device_path") or self.usb_index
                for preset in presets:
                    for name, backend in backend_candidates:
                        cap = cv2.VideoCapture(open_target, backend)
                        if not cap.isOpened():
                            cap.release()
                            continue

                        # Apply preset properties
                        width = preset.get("width")
                        height = preset.get("height")
                        fps = preset.get("fps")
                        fourcc = preset.get("fourcc")

                        if fourcc:
                            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*str(fourcc)))
                        if width:
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
                        if height:
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
                        if fps:
                            cap.set(cv2.CAP_PROP_FPS, float(fps))

                        # Reduce buffering if supported
                        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        actual_fps = cap.get(cv2.CAP_PROP_FPS)

                        # Simple warmup - just verify camera can read at least once
                        ok = False
                        for _ in range(warmup_reads):
                            ok, _ = cap.read()
                            if ok:
                                break
                            time.sleep(0.1)
                        if not ok:
                            cap.release()
                            continue

                        # Reject cameras that stay at high resolution (USB bandwidth issue)
                        if self.reject_high_res and actual_w > 640:
                            print(f"[CAM_{self.face}] Rejecting {actual_w}x{actual_h} - resolution too high (need ≤640)")
                            cap.release()
                            continue

                        # Reject cameras that report excessively high FPS
                        if self.reject_high_fps and actual_fps > 30:
                            print(f"[CAM_{self.face}] Rejecting @ {actual_fps}fps - FPS too high (need ≤30)")
                            cap.release()
                            continue

                        self.cap = cap
                        used_backend_name = name
                        break
                    if self.cap is not None and self.cap.isOpened():
                        break

                # Brief settle delay before next camera opens
                if self.cap is not None and self.cap.isOpened():
                    time.sleep(0.3)
            finally:
                if self.open_semaphore is not None:
                    self.open_semaphore.release()
            
            if self.cap is not None and self.cap.isOpened():
                self.is_connected = True
                self.reconnect_attempts = 0
                self.reconnect_backoff_s = 0.5
                actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
                open_desc = self.capture_settings.get("device_path") or f"USB {self.usb_index}"
                print(
                    f"[CAM_{self.face}] Connected to {open_desc} "
                    f"({actual_w}x{actual_h} @ {actual_fps:.1f}fps, backend={used_backend_name or backend_name})"
                )
                return True
            else:
                open_desc = self.capture_settings.get("device_path") or f"USB index {self.usb_index}"
                print(
                    f"[CAM_{self.face}] Failed to open {open_desc} "
                    f"(backend={backend_name})"
                )
                return False
                
        except Exception as e:
            print(f"[CAM_{self.face}] Connection error: {e}")
            return False
    
    def reconnect(self) -> bool:
        """Attempt to reconnect after disconnect."""
        self.reconnect_attempts += 1
        print(
            f"[CAM_{self.face}] Reconnect attempt {self.reconnect_attempts} "
            f"(backoff {self.reconnect_backoff_s:.1f}s)"
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
        else:
            # Reset backoff on success
            self.reconnect_backoff_s = self.reconnect_backoff_initial
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
            cx, cy = roi['cx'], roi['cy']
            w = roi.get('w', roi.get('radius', 20))
            h = roi.get('h', roi.get('radius', 20))
            angle = roi.get('angle', 0)
            
            # Determine status/color
            det = det_map.get(hole_id)
            if det:
                if det['laser']:
                    color = (0, 255, 0)  # Green - stable detection
                elif det['raw_detection']:
                    color = (0, 255, 255)  # Yellow - detected but unstable
                elif self.target_hole_id == hole_id:
                    color = (255, 255, 0)  # Cyan - Target
                else:
                    color = (0, 0, 255)  # Red - processed but no laser
            else:
                color = (128, 128, 128)  # Gray - no detection info yet
            
            # Draw shape
            if w == h:
                cv2.circle(display, (cx, cy), w, color, 2)
            else:
                cv2.ellipse(display, (cx, cy), (w, h), angle, 0, 360, color, 2)
            
            # Draw label
            label = f"{hole_id}"
            if det and det['laser']:
                label += " OK"
            cv2.putText(display, label, (cx - 20, cy - max(w, h) - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # Draw camera info
        info = f"CAM_{self.face} | FPS: {self.fps_actual:.1f} | Frame: {self.frame_count}"
        cv2.putText(display, info, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return display
    
    def run(self):
        """Main capture loop. Call this in a separate process."""
        print(f"[CAM_{self.face}] Starting worker...")
        
        # Load ROIs
        self.load_rois()
        
        # Initial connection
        if not self.connect():
            print(f"[CAM_{self.face}] Initial connection failed. Will retry...")
        
        last_fps_time = time.time()
        fps_frame_count = 0
        
        while not self.control_event.is_set():
            # Check connection
            if not self.is_connected:
                if not self.reconnect():
                    time.sleep(1)
                    continue
            
            # Read frame with extended retry in robust mode
            ret, frame = self.cap.read()
            if not ret:
                retry_ok = False
                retry_count = self.max_read_retries if self.robust_mode else 2
                for attempt in range(retry_count):
                    time.sleep(0.05)
                    ret, frame = self.cap.read()
                    if ret:
                        retry_ok = True
                        break
                if not retry_ok:
                    if self.robust_mode:
                        # In robust mode, keep trying without triggering reconnect
                        time.sleep(0.1)
                        continue
                    else:
                        print(f"[CAM_{self.face}] Frame read failed. Attempting reconnect...")
                        self.is_connected = False
                        if self.cap:
                            self.cap.release()
                        continue
            
            self.frame_count += 1
            fps_frame_count += 1
            
            # Calculate actual FPS
            now = time.time()
            if now - last_fps_time >= 1.0:
                self.fps_actual = fps_frame_count / (now - last_fps_time)
                fps_frame_count = 0
                last_fps_time = now
            
            # Check commands
            if self.command_queue:
                try:
                    cmd = self.command_queue.get_nowait()
                    if cmd.get('action') == 'set_target':
                        self.target_hole_id = cmd.get('hole_id')
                except:
                    pass

            if self.display_queue:
                if (now - self.last_display_time) >= self.display_interval:
                    try:
                        # Draw overlays using the most recent detections
                        display_frame = self.draw_overlays(frame, self.last_detections)
                        # Only resize if frame is larger than display_size
                        fh, fw = display_frame.shape[:2]
                        dw, dh = self.display_size
                        if fw != dw or fh != dh:
                            small = cv2.resize(display_frame, self.display_size)
                        else:
                            small = display_frame
                        self.display_queue.put_nowait((f"CAM_{self.face}", small))
                        self.last_display_time = now
                    except:
                        pass  # Queue full, skip this display frame
            
            # Frame throttling - skip PROCESSING if running faster than target_fps
            # Processing is more expensive (blob detection), so throttle more aggressively
            if self.frame_interval > 0 and (now - self.last_process_time) < self.frame_interval:
                continue  # Skip processing, but display was already sent above
            # Check commands
            if self.command_queue:
                try:
                    cmd = self.command_queue.get_nowait()
                    if cmd.get('action') == 'set_target':
                        self.target_hole_id = cmd.get('hole_id')
                except:
                    pass

            self.last_process_time = now
            
            # Process frame (blob detection - expensive operation)
            result = self.process_frame(frame)
            self.last_detections = result['detections']
            
            # Send result to queue (non-blocking)
            try:
                self.result_queue.put_nowait(result)
            except:
                pass  # Queue full, skip this result
        
        # Cleanup
        if self.cap:
            self.cap.release()
        print(f"[CAM_{self.face}] Worker stopped.")


def camera_worker_process(usb_index: int, face: str, config_file: str,
                          result_queue, control_event, display_queue=None,
                          capture_settings: Optional[Dict[str, Any]] = None,
                          hub_id: Optional[int] = None,
                          open_semaphore=None,
                          command_queue=None):
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
        command_queue=command_queue
    )
    worker.run()

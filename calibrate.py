"""
ROI Calibration Tool
Saves to: config/rois_webcam.json (default, configurable via --config)

Supports ELLIPSES for perspective correction.

Controls:
- Drag to move selected ellipse
- +/- : increase/decrease width
- [/] : increase/decrease height  
- LEFT/RIGHT arrows: rotate ellipse ±5°
- 'a' add | 'd' delete | 'c' copy
- 'n' rename (on-screen input)
- 's' SAVE | 'q' quit | SPACE refresh
"""

import cv2
import numpy as np
import os
import json
import argparse

DEFAULT_CONFIG_PATH = "config/rois_webcam.json"
DEFAULT_ELLIPSES = [{'name': 'H1', 'cx': 320, 'cy': 240, 'w': 40, 'h': 40, 'angle': 0}]

# Module-level config path, set by CLI
CONFIG_PATH = DEFAULT_CONFIG_PATH

class Calibrator:
    def __init__(self, cam_idx=0):
        self.cam_idx = cam_idx
        self.ellipses = []
        self.selected_idx = -1
        self.dragging = False
        self.drag_offset = (0, 0)
        self.mouse_pos = (0, 0)
        self.original_frame = None
        self.cap = None
        self.renaming = False
        self.rename_text = ""
        self.show_legend = True

    def load_config(self):
        """Load ROIs from circles format: {"circles": [{"name": "H1", "coords": [cx, cy, r]}]}"""
        self.ellipses = []
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    data = json.load(f)
                
                # Load from circles format (what camera_worker.py uses)
                raw_circles = data.get('circles', [])
                for i, c in enumerate(raw_circles):
                    if isinstance(c, list):
                        # Old format: [cx, cy, r]
                        cx, cy, r = c
                        name = f"H{i+1}"
                    elif isinstance(c, dict):
                        # New format: {"name": "H1", "coords": [cx, cy, r]}
                        name = c.get('name', f"H{i+1}")
                        cx, cy, r = c['coords']
                    else:
                        continue
                    self.ellipses.append({
                        'name': name,
                        'cx': cx, 'cy': cy,
                        'w': r, 'h': r,
                        'angle': 0
                    })
                
                # Fallback: also try rois format for backward compatibility
                if not self.ellipses:
                    for r in data.get('rois', []):
                        self.ellipses.append({
                            'name': r.get('hole_id', 'H1'),
                            'cx': r.get('cx', 320),
                            'cy': r.get('cy', 240),
                            'w': r.get('w', r.get('radius', 40)),
                            'h': r.get('h', r.get('radius', 40)),
                            'angle': r.get('angle', 0)
                        })
                
                if self.ellipses:
                    print(f"[INFO] Loaded {len(self.ellipses)} ROIs from {CONFIG_PATH}")
            except Exception as e:
                print(f"[WARN] Failed to load: {e}")
        if not self.ellipses:
            self.ellipses = [e.copy() for e in DEFAULT_ELLIPSES]
            print("[INFO] Starting with default ellipse.")

    def save_config(self):
        """Save ROIs in circles format with ellipse data:
        {"circles": [...], "calibration_resolution": [640, 480]}
        Compatible with camera_worker.py — uses w/h/angle for ellipses, falls back to radius for circles."""
        circles = []
        for e in self.ellipses:
            radius = int((e['w'] + e['h']) / 2)
            entry = {
                "name": e['name'],
                "coords": [int(e['cx']), int(e['cy']), radius],
                "w": int(e['w']),
                "h": int(e['h']),
                "angle": int(e['angle'])
            }
            circles.append(entry)
        with open(CONFIG_PATH, 'w') as f:
            json.dump({"circles": circles, "calibration_resolution": [640, 480]}, f, indent=2)
        print(f"[SUCCESS] Saved {len(circles)} ROIs to {CONFIG_PATH}")

    def get_ellipse_at(self, x, y):
        for i, e in enumerate(self.ellipses):
            dx = x - e['cx']
            dy = y - e['cy']
            if dx*dx + dy*dy <= max(e['w'], e['h'])**2:
                return i
        return -1

    def mouse_callback(self, event, x, y, flags, param):
        self.mouse_pos = (x, y)
        if self.renaming:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            idx = self.get_ellipse_at(x, y)
            if idx >= 0:
                self.selected_idx = idx
                self.dragging = True
                e = self.ellipses[idx]
                self.drag_offset = (e['cx'] - x, e['cy'] - y)
            else:
                self.selected_idx = -1
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging and self.selected_idx >= 0:
            self.ellipses[self.selected_idx]['cx'] = x + self.drag_offset[0]
            self.ellipses[self.selected_idx]['cy'] = y + self.drag_offset[1]
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False

    def draw_frame(self):
        if self.original_frame is None:
            return np.zeros((480, 640, 3), dtype=np.uint8)
        display = self.original_frame.copy()
        h, w = display.shape[:2]
        
        for i, e in enumerate(self.ellipses):
            color = (0, 255, 0) if i == self.selected_idx else (0, 255, 255)
            center = (int(e['cx']), int(e['cy']))
            axes = (int(e['w']), int(e['h']))
            angle = int(e['angle'])
            cv2.ellipse(display, center, axes, angle, 0, 360, color, 2 if i != self.selected_idx else 3)
            cv2.circle(display, center, 3, (0, 0, 255), -1)
            cv2.putText(display, e['name'], (center[0]-10, center[1]-max(e['w'],e['h'])-10), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        
        # Info panel - Moved to bottom left, smaller, toggleable
        if self.show_legend:
            cv2.rectangle(display, (0, 420), (280, 480), (0, 0, 0), -1)
            cv2.rectangle(display, (0, 420), (280, 480), (0, 255, 0), 1)
            
            sel_info = "None"
            if self.selected_idx >= 0:
                e = self.ellipses[self.selected_idx]
                sel_info = f"{e['name']}"
            
            lines = [
                f"Count: {len(self.ellipses)} | Sel: {sel_info}",
                "Drag: Move | +/-: Size | [/]: Height",
                "Arrows: Rotate | n: Rename",
                "a: Add | d: Delete | c: Copy",
                "s: SAVE | h: Hide Legend | q: Quit"
            ]
            for i, line in enumerate(lines):
                cv2.putText(display, line, (5, 430 + i*15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        
        if self.renaming and self.selected_idx >= 0:
            cv2.rectangle(display, (200, 300), (600, 360), (50, 50, 50), -1)
            cv2.rectangle(display, (200, 300), (600, 360), (0, 255, 0), 2)
            cv2.putText(display, f"Rename: {self.rename_text}_", (210, 340), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        return display

    def run(self):
        self.cap = cv2.VideoCapture(self.cam_idx)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not self.cap.isOpened():
            print(f"[ERROR] Cannot open camera {self.cam_idx}")
            return
        
        # Verify resolution
        actual_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"[INFO] Camera {self.cam_idx} resolution: {int(actual_w)}x{int(actual_h)}")
        
        self.load_config()
        ret, self.original_frame = self.cap.read()
        if not ret:
            print("[ERROR] Cannot read frame")
            return

        win = "ROI Calibration (Ellipse)"
        cv2.namedWindow(win)
        cv2.setMouseCallback(win, self.mouse_callback)

        while True:
            cv2.imshow(win, self.draw_frame())
            key = cv2.waitKey(20) & 0xFF
            
            if self.renaming:
                if key == 27:
                    self.renaming = False
                    self.rename_text = ""
                elif key == 13 or key == 10:  # Enter (Windows/Linux or Mac)
                    if self.rename_text and self.selected_idx >= 0:
                        self.ellipses[self.selected_idx]['name'] = self.rename_text
                    self.renaming = False
                    self.rename_text = ""
                elif key == 8 or key == 127:  # Backspace (Windows/Linux or Mac)
                    self.rename_text = self.rename_text[:-1]
                elif 32 <= key <= 126:
                    self.rename_text += chr(key)
                continue
            
            if key == ord('q') or key == 27:
                break
            elif key == ord('s'):
                self.save_config()
            elif key == ord('a'):
                self.ellipses.append({'name': f"H{len(self.ellipses)+1}", 
                                     'cx': self.mouse_pos[0], 'cy': self.mouse_pos[1],
                                     'w': 40, 'h': 40, 'angle': 0})
                self.selected_idx = len(self.ellipses) - 1
            elif key == ord('d') and self.selected_idx >= 0:
                del self.ellipses[self.selected_idx]
                self.selected_idx = -1
            elif key == ord('c') and self.selected_idx >= 0:
                e = self.ellipses[self.selected_idx]
                self.ellipses.append({'name': f"H{len(self.ellipses)+1}",
                                     'cx': e['cx']+20, 'cy': e['cy']+20,
                                     'w': e['w'], 'h': e['h'], 'angle': e['angle']})
                self.selected_idx = len(self.ellipses) - 1
            elif key == ord('h'):
                self.show_legend = not self.show_legend
            elif key == ord('n') and self.selected_idx >= 0:
                self.renaming = True
                self.rename_text = ""
            elif key == ord('+') or key == ord('='):
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['w'] += 2
            elif key == ord('-') or key == ord('_'):
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['w'] = max(5, self.ellipses[self.selected_idx]['w'] - 2)
            elif key == ord(']'):
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['h'] += 2
            elif key == ord('['):
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['h'] = max(5, self.ellipses[self.selected_idx]['h'] - 2)
            elif key == 81 or key == 2:  # LEFT
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['angle'] -= 5
            elif key == 83 or key == 3:  # RIGHT
                if self.selected_idx >= 0: self.ellipses[self.selected_idx]['angle'] += 5
            elif key == ord(' '):
                ret, self.original_frame = self.cap.read()

        self.cap.release()
        cv2.destroyAllWindows()

def resolve_config_from_cameras_json(cam_idx, cameras_json="config/cameras.json"):
    """Look up the per-camera config file from cameras.json.
    
    Files are at project root (main.py resolves config/../filename = root).
    """
    if not os.path.exists(cameras_json):
        return None
    try:
        with open(cameras_json, 'r') as f:
            data = json.load(f)
        for cam in data.get("cameras", []):
            if cam.get("usb_index") == cam_idx and cam.get("enabled", True):
                config_file = cam.get("config")
                if config_file:
                    # Files live at project root, same as main.py resolves them
                    return config_file
    except Exception:
        pass
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ROI Calibration Tool")
    parser.add_argument("--cam", type=int, default=0, help="Camera index")
    parser.add_argument("--config", type=str, default=None, help="ROI config file path (auto-detected from cameras.json if omitted)")
    args = parser.parse_args()

    if args.config:
        CONFIG_PATH = args.config
    else:
        resolved = resolve_config_from_cameras_json(args.cam)
        if resolved:
            CONFIG_PATH = resolved
            print(f"[AUTO] Camera {args.cam} → config: {CONFIG_PATH}")
        else:
            CONFIG_PATH = DEFAULT_CONFIG_PATH
            print(f"[WARN] No cameras.json match for cam {args.cam}, using default: {CONFIG_PATH}")

    Calibrator(args.cam).run()

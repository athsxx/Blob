"""In-app freeze-and-drag hole ROI editor.

Setup (start screen): opens one USB camera at the capture-profile size, freezes
a frame, then releases. Live workers must not be running.

Live session: snapshot from the worker that already owns the device. Never a
second VideoCapture while workers are alive.
"""
from __future__ import annotations

import json
import math
import os
import queue
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from PyQt6.QtCore import Qt, QRect, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from capture_profile import load_capture_profile
from config_loader import (
    face_roi_basename,
    hole_ids_for_face,
    load_rules,
    manifold_data_subdirectory,
    manifold_folder_for_label,
)
from session_overlay import SessionBusyOverlay

SNAPSHOT_TIMEOUT_S = 5.0
APPLY_TIMEOUT_S = 3.0
FACE_ORDER = "ABCDEF"
DEFAULT_AXIS = 40.0
MIN_AXIS = 5.0
AXIS_STEP = 2.0
ROTATE_STEP = 5.0
MAX_INTEGER_SCALE = 3

# Godrej light tokens — freeze overlay (UI is light; do not use dark GitHub hex)
PAPER = QColor("#fafaf7")
INK = QColor("#0f1216")
PLUM = QColor("#810055")
NAVY = QColor("#0e2742")


def grab_setup_snapshot(usb_index: int, config_dir: str, process_events=None):
    """
    Open one camera, grab a warmed frame at the locked capture size, release.

    Same MJPG / width / height as live workers so saved ellipses match detection.
    """
    import cv2

    profile = load_capture_profile(config_dir)
    width = int(profile.get("width") or 320)
    height = int(profile.get("height") or 240)
    fps = float(profile.get("fps") or 5)
    if sys.platform == "win32":
        backend = cv2.CAP_DSHOW
    elif sys.platform == "darwin":
        backend = cv2.CAP_AVFOUNDATION
    else:
        backend = cv2.CAP_ANY
    cap = None
    frame = None
    prev_log = None
    try:
        prev_log = cv2.utils.logging.getLogLevel()
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        prev_log = None
    try:
        cap = cv2.VideoCapture(int(usb_index), backend)
        if cap is None or not cap.isOpened():
            return None
        if sys.platform == "win32":
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
        for i in range(20):
            if process_events is not None:
                process_events()
            ok, im = cap.read()
            if ok and im is not None and getattr(im, "size", 0) > 0:
                frame = im
            elif i == 0:
                time.sleep(0.4)
            else:
                time.sleep(0.05)
        return None if frame is None else frame.copy()
    except Exception:
        return None
    finally:
        if cap is not None:
            cap.release()
        if prev_log is not None:
            try:
                cv2.utils.logging.setLogLevel(prev_log)
            except Exception:
                pass
        time.sleep(0.3)


def _bgr_to_qimage(frame: np.ndarray) -> QImage:
    h, w = frame.shape[:2]
    rgb = np.ascontiguousarray(frame[..., ::-1])
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _load_circles(path: str) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[int]]:
    if not os.path.isfile(path):
        return [], None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return [], None, None
    calib_w = data.get("calib_width")
    calib_h = data.get("calib_height")
    ellipses: List[Dict[str, Any]] = []
    for i, c in enumerate(data.get("circles") or []):
        if isinstance(c, list) and len(c) >= 3:
            cx, cy, r = c[0], c[1], c[2]
            ellipses.append({"name": f"H{i+1}", "cx": float(cx), "cy": float(cy), "w": float(r), "h": float(r), "angle": 0.0})
        elif isinstance(c, dict) and "coords" in c:
            coords = c.get("coords") or [0, 0, 8]
            cx, cy, r = coords[0], coords[1], coords[2] if len(coords) > 2 else 8
            ellipses.append({
                "name": str(c.get("name") or f"H{i+1}"),
                "cx": float(cx),
                "cy": float(cy),
                "w": float(c.get("w", r)),
                "h": float(c.get("h", r)),
                "angle": float(c.get("angle", 0)),
            })
    return ellipses, (int(calib_w) if calib_w else None), (int(calib_h) if calib_h else None)


def _save_circles(path: str, ellipses: List[Dict[str, Any]], width: int, height: int) -> None:
    circles = []
    for e in ellipses:
        radius = int(round((float(e["w"]) + float(e["h"])) / 2.0))
        circles.append({
            "name": e["name"],
            "coords": [int(round(e["cx"])), int(round(e["cy"])), max(1, radius)],
            "w": int(round(e["w"])),
            "h": int(round(e["h"])),
            "angle": int(round(e["angle"])),
        })
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"calib_width": int(width), "calib_height": int(height), "circles": circles},
            f,
            indent=2,
        )
        f.write("\n")


def _inside_ellipse(e: Dict[str, Any], x: float, y: float, pad: float = 1.2) -> bool:
    dx = x - float(e["cx"])
    dy = y - float(e["cy"])
    ang = math.radians(-float(e.get("angle", 0)))
    rx = dx * math.cos(ang) - dy * math.sin(ang)
    ry = dx * math.sin(ang) + dy * math.cos(ang)
    w = max(1.0, float(e["w"]))
    h = max(1.0, float(e["h"]))
    return (rx / w) ** 2 + (ry / h) ** 2 <= pad


class RoiCanvas(QWidget):
    """Freeze canvas: mouse selects/moves; keyboard sizes and rotates (calibrate.py)."""

    edited = pyqtSignal()
    holes_changed = pyqtSignal()
    recapture_requested = pyqtSignal()
    add_at_cursor = pyqtSignal(float, float)
    copy_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._image: Optional[QImage] = None
        self._img_w = 1
        self._img_h = 1
        self.ellipses: List[Dict[str, Any]] = []
        self.selected = -1
        self._drag = None
        self._grab = (0.0, 0.0)
        self.place_name: Optional[str] = None
        self.busy = False
        self.cursor_xy: Tuple[float, float] = (0.0, 0.0)

    def set_frame(self, frame: np.ndarray) -> None:
        self._img_h, self._img_w = frame.shape[:2]
        self._image = _bgr_to_qimage(frame)
        self.cursor_xy = (self._img_w / 2.0, self._img_h / 2.0)
        self.update()

    def _integer_scale(self) -> int:
        wr, hr = self.width(), self.height()
        sx = wr // max(self._img_w, 1)
        sy = hr // max(self._img_h, 1)
        return max(1, min(sx, sy, MAX_INTEGER_SCALE))

    def _dest_rect(self) -> QRect:
        if self._image is None:
            return QRect()
        scale = self._integer_scale()
        dw, dh = self._img_w * scale, self._img_h * scale
        return QRect((self.width() - dw) // 2, (self.height() - dh) // 2, dw, dh)

    def _to_image(self, pos: QPoint) -> Optional[Tuple[float, float]]:
        rect = self._dest_rect()
        scale = self._integer_scale()
        if rect.width() <= 0 or rect.height() <= 0 or scale <= 0:
            return None
        if not rect.contains(pos):
            return None
        x = (pos.x() - rect.x()) / float(scale)
        y = (pos.y() - rect.y()) / float(scale)
        return x, y

    def selected_ellipse(self) -> Optional[Dict[str, Any]]:
        if 0 <= self.selected < len(self.ellipses):
            return self.ellipses[self.selected]
        return None

    def paintEvent(self, event) -> None:  # noqa: ARG002
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), PAPER)
            rect = self._dest_rect()
            if self._image is not None and rect.isValid():
                p.drawImage(rect, self._image)
            if self._image is None:
                p.setPen(INK)
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Waiting for snapshot")
                return
            scale = float(self._integer_scale())

            def map_pt(x, y) -> QPoint:
                return QPoint(
                    rect.x() + int(round(float(x) * scale)),
                    rect.y() + int(round(float(y) * scale)),
                )

            for i, e in enumerate(self.ellipses):
                try:
                    self._paint_ellipse(p, e, i == self.selected, scale, map_pt)
                except Exception:
                    continue

            self._paint_overlay(p)
        except Exception:
            return
        finally:
            p.end()

    def _paint_ellipse(self, p, e, selected, scale, map_pt) -> None:
        color = PLUM if selected else NAVY
        pen = QPen(color)
        pen.setWidth(3 if selected else 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        center = map_pt(float(e["cx"]), float(e["cy"]))
        p.save()
        try:
            p.translate(center)
            p.rotate(float(e.get("angle", 0) or 0))
            p.drawEllipse(
                QPoint(0, 0),
                max(2, int(round(float(e["w"]) * scale))),
                max(2, int(round(float(e["h"]) * scale))),
            )
        finally:
            p.restore()
        p.setBrush(PLUM if selected else NAVY)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(center, 3, 3)
        p.setPen(INK)
        lift = max(float(e["w"]), float(e["h"])) * scale
        p.drawText(center.x() - 10, center.y() - int(lift) - 8, str(e.get("name") or ""))

    def _paint_overlay(self, p) -> None:
        e = self.selected_ellipse()
        if e is not None:
            readout = (
                f"{e.get('name') or '?'}  w={int(round(float(e['w'])))}  "
                f"h={int(round(float(e['h'])))}  angle={int(round(float(e.get('angle', 0))))}°"
            )
        else:
            readout = "No selection"
        if self.place_name:
            readout = f"Click to place {self.place_name}  ·  {readout}"
        legend = (
            "Drag: move  |  +/-: width  |  [/]: height  |  arrows: rotate  |  "
            "a: add  |  c: copy  |  d: delete  |  SPACE: recapture"
        )
        p.setPen(Qt.PenStyle.NoPen)
        panel = QColor(PAPER)
        panel.setAlpha(230)
        box = QRect(8, self.height() - 52, max(280, self.width() - 16), 44)
        p.setBrush(panel)
        p.drawRect(box)
        p.setPen(QPen(PLUM, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(box)
        p.setPen(INK)
        p.drawText(box.adjusted(8, 4, -8, -20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, readout)
        p.drawText(box.adjusted(8, 22, -8, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, legend)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.busy:
            return
        img = self._to_image(event.position().toPoint())
        if img is None:
            if self.place_name:
                return
            self.selected = -1
            self.edited.emit()
            self.update()
            return
        x, y = img
        self.cursor_xy = (x, y)
        if self.place_name:
            self.ellipses.append({
                "name": self.place_name,
                "cx": x,
                "cy": y,
                "w": DEFAULT_AXIS,
                "h": DEFAULT_AXIS,
                "angle": 0.0,
            })
            self.selected = len(self.ellipses) - 1
            self.place_name = None
            self.holes_changed.emit()
            self.edited.emit()
            self.update()
            return
        for i in range(len(self.ellipses) - 1, -1, -1):
            if _inside_ellipse(self.ellipses[i], x, y):
                self.selected = i
                self._drag = "move"
                self._grab = (x - self.ellipses[i]["cx"], y - self.ellipses[i]["cy"])
                self.edited.emit()
                self.update()
                return
        self.selected = -1
        self.edited.emit()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        img = self._to_image(event.position().toPoint())
        if img is not None:
            self.cursor_xy = img
        if self.busy or self._drag != "move" or self.selected < 0:
            return
        if img is None:
            return
        x, y = img
        e = self.ellipses[self.selected]
        e["cx"] = x - self._grab[0]
        e["cy"] = y - self._grab[1]
        self.edited.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: ARG002
        self._drag = None

    def _nudge_axis(self, axis: str, delta: float) -> None:
        e = self.selected_ellipse()
        if e is None:
            return
        e[axis] = max(MIN_AXIS, float(e[axis]) + delta)
        self.edited.emit()
        self.update()

    def _nudge_angle(self, delta: float) -> None:
        e = self.selected_ellipse()
        if e is None:
            return
        e["angle"] = float(e.get("angle", 0) or 0) + delta
        self.edited.emit()
        self.update()

    def _delete_selected(self) -> None:
        if self.selected < 0:
            return
        del self.ellipses[self.selected]
        self.selected = -1
        self.holes_changed.emit()
        self.edited.emit()
        self.update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.busy:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self._nudge_axis("w", AXIS_STEP)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self._nudge_axis("w", -AXIS_STEP)
        elif key == Qt.Key.Key_BracketRight:
            self._nudge_axis("h", AXIS_STEP)
        elif key == Qt.Key.Key_BracketLeft:
            self._nudge_axis("h", -AXIS_STEP)
        elif key == Qt.Key.Key_Left:
            self._nudge_angle(-ROTATE_STEP)
        elif key == Qt.Key.Key_Right:
            self._nudge_angle(ROTATE_STEP)
        elif key == Qt.Key.Key_A:
            x, y = self.cursor_xy
            self.add_at_cursor.emit(x, y)
        elif key == Qt.Key.Key_C:
            self.copy_requested.emit()
        elif key in (Qt.Key.Key_D, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
        elif key == Qt.Key.Key_Space:
            self.recapture_requested.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()


def wait_worker_event(snap_q, face: str, action: str, timeout_s: float) -> Optional[dict]:
    from PyQt6.QtWidgets import QApplication

    deadline = time.time() + timeout_s
    face = str(face).upper()
    leftover = []
    found = None
    while time.time() < deadline:
        QApplication.processEvents()
        try:
            msg = snap_q.get_nowait()
        except queue.Empty:
            time.sleep(0.03)
            continue
        if not isinstance(msg, dict):
            continue
        if str(msg.get("face", "")).upper() == face and msg.get("action") == action:
            found = msg
            break
        leftover.append(msg)
    for item in leftover:
        try:
            snap_q.put_nowait(item)
        except Exception:
            break
    return found


class RoiEditorDialog(QDialog):
    """Setup-page ROI session: one camera at a time, then release. Live workers must not be running."""

    def __init__(
        self,
        manifold: str,
        config_dir: str,
        cameras: List[Dict[str, Any]],
        comm_queues: Optional[Dict[str, Any]] = None,
        snapshot_queue=None,
        stylesheet: str = "",
        parent=None,
        setup_mode: bool = False,
    ):
        super().__init__(parent)
        self._manifold = manifold
        self._config_dir = config_dir
        self._cameras = cameras
        self._comm = comm_queues or {}
        self._snap_q = snapshot_queue
        self._setup_mode = bool(setup_mode) or not self._comm
        self._busy_flag = False
        self._frame_size = (320, 240)
        self._subdir = manifold_data_subdirectory(manifold, config_dir)
        folder = manifold_folder_for_label(manifold, config_dir) or self._subdir
        self._rules = load_rules(os.path.join(config_dir, folder, "connectivity_rules.json"))

        self.setWindowTitle("Edit hole ROIs")
        self.resize(980, 720)
        if stylesheet:
            self.setStyleSheet(stylesheet)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        if self._setup_mode:
            hint_text = (
                "Cameras are closed except the face you are editing. Click the freeze first so keys work. "
                "Click to drop or move; +/- width; [ ] height; arrows rotate; a add; c copy; d delete; "
                "SPACE recapture (opens this face once, then releases). Hole names come from the rule list."
            )
        else:
            hint_text = (
                "Cameras stay open. Click the freeze first so keys work. "
                "Click to drop or move; +/- width; [ ] height; arrows rotate; a add; c copy; d delete. "
                "Hole names come from connectivity rules."
            )
        hint = QLabel(hint_text)
        hint.setObjectName("pageHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        tools = QHBoxLayout()
        tools.addWidget(QLabel("Face"))
        self.face_combo = QComboBox()
        self.face_combo.setObjectName("pageCombo")
        self.face_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        enabled = {
            str(c.get("face", "")).upper()
            for c in cameras
            if c.get("enabled", True) and c.get("face")
        }
        for letter in FACE_ORDER:
            if letter not in enabled:
                continue
            if not self._setup_mode and letter not in self._comm:
                continue
            if self._setup_mode and self._usb_index(letter) is None:
                continue
            n_holes = len(hole_ids_for_face(self._rules, letter))
            self.face_combo.addItem(f"Face {letter}  ({n_holes} rule holes)", userData=letter)
        tools.addWidget(self.face_combo)

        tools.addWidget(QLabel("Hole"))
        self.hole_combo = QComboBox()
        self.hole_combo.setObjectName("pageCombo")
        self.hole_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tools.addWidget(self.hole_combo, stretch=1)

        self.btn_place = QPushButton("Place on image")
        self.btn_place.setObjectName("pageSecondary")
        self.btn_place.clicked.connect(self._on_place)
        self.btn_delete = QPushButton("Delete selected")
        self.btn_delete.setObjectName("pageSecondary")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_save = QPushButton("Save")
        self.btn_save.setObjectName("pagePrimary")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("pageGhost")
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_place, self.btn_delete, self.btn_save, self.btn_close):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoDefault(False)
            b.setDefault(False)
            tools.addWidget(b)
        root.addLayout(tools)

        self.status = QLabel("Capturing snapshot…")
        self.status.setObjectName("pageMeta")
        root.addWidget(self.status)
        self.readout = QLabel("No selection")
        self.readout.setObjectName("pageMeta")
        root.addWidget(self.readout)

        self.canvas = RoiCanvas(self)
        self.canvas.edited.connect(self._update_readout)
        self.canvas.holes_changed.connect(lambda: self._refresh_hole_combo(self._current_face()))
        self.canvas.add_at_cursor.connect(self._on_add_at_cursor)
        self.canvas.copy_requested.connect(self._on_copy)
        self.canvas.recapture_requested.connect(self._on_recapture)
        root.addWidget(self.canvas, stretch=1)

        self._overlay = SessionBusyOverlay(self)
        self.face_combo.currentIndexChanged.connect(self._on_face_changed)
        if self.face_combo.count() == 0:
            if self._setup_mode:
                self.status.setText("Assign camera faces first, then edit hole ROIs.")
            else:
                self.status.setText("No live camera workers. Return to the start screen to edit ROIs.")
        else:
            QTimer.singleShot(0, self._capture_current_face)

    def _usb_index(self, face: str) -> Optional[int]:
        for cam in self._cameras:
            if str(cam.get("face", "")).upper() != str(face).upper():
                continue
            if cam.get("usb_index") is None:
                return None
            return int(cam["usb_index"])
        return None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())

    def _current_face(self) -> str:
        return str(self.face_combo.currentData() or "A")

    def _roi_path(self, face: str) -> str:
        return os.path.normpath(os.path.join(self._config_dir, self._subdir, face_roi_basename(face)))

    def _set_busy(self, on: bool, title: str = "", detail: str = "") -> None:
        self._busy_flag = on
        self.canvas.busy = on
        for w in (self.face_combo, self.hole_combo, self.btn_place, self.btn_delete, self.btn_save):
            w.setEnabled(not on)
        if on:
            self._overlay.show_message(title, detail)
        else:
            self._overlay.clear()
            self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refresh_hole_combo(self, face: str) -> None:
        used = {e["name"] for e in self.canvas.ellipses}
        self.hole_combo.clear()
        names = hole_ids_for_face(self._rules, face)
        if not names:
            self.hole_combo.addItem("(no rule holes for this face)", userData="")
            return
        for name in names:
            suffix = " — placed" if name in used else ""
            self.hole_combo.addItem(f"{name}{suffix}", userData=name)

    def _on_face_changed(self) -> None:
        if self._busy_flag:
            return
        self._capture_current_face()

    def _capture_current_face(self, keep_ellipses: bool = False) -> None:
        face = self._current_face()
        if self._setup_mode:
            self._capture_setup_face(face, keep_ellipses=keep_ellipses)
            return
        cq = self._comm.get(face)
        if cq is None or self._snap_q is None:
            self.status.setText(f"Face {face} has no live worker.")
            QMessageBox.warning(self, "Edit hole ROIs", f"Face {face} is not running. Cameras were not killed.")
            return
        self._set_busy(True, "Capturing snapshot…", f"Face {face}. Do not close the main window.")
        self.status.setText(f"Capturing Face {face}…")
        try:
            cq.put({"action": "snapshot"})
        except Exception as exc:
            self._set_busy(False)
            QMessageBox.warning(self, "Edit hole ROIs", f"Could not request snapshot: {exc}")
            return
        msg = wait_worker_event(self._snap_q, face, "snapshot", SNAPSHOT_TIMEOUT_S)
        self._set_busy(False)
        if not msg or not msg.get("ok") or msg.get("frame") is None:
            self.status.setText("No frame — cameras are still running.")
            QMessageBox.warning(
                self,
                "Edit hole ROIs",
                f"No snapshot from Face {face} within {int(SNAPSHOT_TIMEOUT_S)}s.\n"
                "Cameras stay up. Try again after the tile shows a picture.",
            )
            return
        self._apply_captured_frame(face, msg["frame"], keep_ellipses=keep_ellipses)

    def _capture_setup_face(self, face: str, keep_ellipses: bool = False) -> None:
        from PyQt6.QtWidgets import QApplication

        usb = self._usb_index(face)
        if usb is None:
            self.status.setText(f"Face {face} has no USB index. Assign camera faces first.")
            QMessageBox.warning(
                self,
                "Edit hole ROIs",
                f"Face {face} has no camera index. Assign camera faces first.",
            )
            return
        self._set_busy(True, "Capturing snapshot…", f"Face {face} USB {usb}. Other cameras stay closed.")
        self.status.setText(f"Opening Face {face} (USB {usb})…")
        frame = grab_setup_snapshot(
            usb,
            self._config_dir,
            process_events=QApplication.processEvents,
        )
        self._set_busy(False)
        if frame is None:
            self.status.setText(f"No frame from Face {face}. Camera was released.")
            QMessageBox.warning(
                self,
                "Edit hole ROIs",
                f"Could not freeze Face {face} (USB {usb}).\n"
                "The camera was released. Check the cable, then try again.",
            )
            return
        self._apply_captured_frame(face, frame, keep_ellipses=keep_ellipses)

    def _apply_captured_frame(self, face: str, frame, keep_ellipses: bool = False) -> None:
        h, w = frame.shape[:2]
        self._frame_size = (w, h)
        self.canvas.set_frame(frame)
        path = self._roi_path(face)
        if not keep_ellipses:
            ellipses, _, _ = _load_circles(path)
            self.canvas.ellipses = ellipses
            self.canvas.selected = 0 if ellipses else -1
            self._refresh_hole_combo(face)
        released = "  ·  camera released" if self._setup_mode else ""
        n = len(self.canvas.ellipses)
        recap = "  ·  freeze recaptured" if keep_ellipses else ""
        self.status.setText(
            f"Face {face}  {w}×{h}  ·  {n} hole(s)  ·  {os.path.basename(path)}{released}{recap}"
        )
        self._update_readout()
        self.canvas.update()
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_place(self) -> None:
        if self._busy_flag:
            return
        name = str(self.hole_combo.currentData() or "").strip()
        if not name:
            QMessageBox.information(self, "Edit hole ROIs", "Pick a hole name from the rule list.")
            return
        existing = next((i for i, e in enumerate(self.canvas.ellipses) if e["name"] == name), -1)
        if existing >= 0:
            self.canvas.selected = existing
            self.canvas.place_name = None
            self.status.setText(f"{name} is already on this face — click and move it onto the hole.")
            self._update_readout()
            self.canvas.update()
            self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        self.canvas.place_name = name
        self.status.setText(f"Click the hole on the image to place {name} (~40×40). Then use keys to size.")
        self.canvas.update()
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _unused_rule_names(self) -> List[str]:
        used = {e["name"] for e in self.canvas.ellipses}
        return [n for n in hole_ids_for_face(self._rules, self._current_face()) if n and n not in used]

    def _combo_hole_name(self) -> str:
        return str(self.hole_combo.currentData() or "").strip()

    def _on_add_at_cursor(self, x: float, y: float) -> None:
        if self._busy_flag:
            return
        name = self._combo_hole_name()
        if not name:
            unused = self._unused_rule_names()
            name = unused[0] if unused else ""
        if not name:
            self.status.setText("Pick a hole name from the rule list.")
            return
        existing = next((i for i, e in enumerate(self.canvas.ellipses) if e["name"] == name), -1)
        if existing >= 0:
            unused = self._unused_rule_names()
            if not unused:
                self.canvas.selected = existing
                self.status.setText(f"{name} is already on this face — all rule holes are placed.")
                self._update_readout()
                self.canvas.update()
                return
            name = unused[0]
        self.canvas.ellipses.append({
            "name": name,
            "cx": x,
            "cy": y,
            "w": DEFAULT_AXIS,
            "h": DEFAULT_AXIS,
            "angle": 0.0,
        })
        self.canvas.selected = len(self.canvas.ellipses) - 1
        self.canvas.place_name = None
        self._refresh_hole_combo(self._current_face())
        self.status.setText(
            f"Placed {name}. Click to move; +/- width; [ ] height; arrows rotate."
        )
        self._update_readout()
        self.canvas.update()

    def _on_copy(self) -> None:
        if self._busy_flag or self.canvas.selected < 0:
            return
        unused = self._unused_rule_names()
        if not unused:
            self.status.setText("Cannot copy — every rule hole on this face is already placed.")
            return
        e = self.canvas.ellipses[self.canvas.selected]
        self.canvas.ellipses.append({
            "name": unused[0],
            "cx": float(e["cx"]) + 20.0,
            "cy": float(e["cy"]) + 20.0,
            "w": float(e["w"]),
            "h": float(e["h"]),
            "angle": float(e.get("angle", 0) or 0),
        })
        self.canvas.selected = len(self.canvas.ellipses) - 1
        self._refresh_hole_combo(self._current_face())
        self.status.setText(f"Copied as {unused[0]} (+20 px).")
        self._update_readout()
        self.canvas.update()

    def _on_recapture(self) -> None:
        if self._busy_flag:
            return
        self._capture_current_face(keep_ellipses=True)

    def _update_readout(self) -> None:
        e = self.canvas.selected_ellipse()
        if e is None:
            self.readout.setText("No selection  ·  click the image for keyboard size/rotate")
            return
        self.readout.setText(
            f"{e.get('name') or '?'}  w={int(round(float(e['w'])))}  "
            f"h={int(round(float(e['h'])))}  angle={int(round(float(e.get('angle', 0) or 0)))}°"
        )

    def _on_delete(self) -> None:
        if self._busy_flag or self.canvas.selected < 0:
            return
        self.canvas._delete_selected()
        self._refresh_hole_combo(self._current_face())
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_save(self) -> None:
        if self._busy_flag:
            return
        face = self._current_face()
        path = self._roi_path(face)
        w, h = self._frame_size
        busy_detail = (
            f"Saving Face {face}. Camera stays closed."
            if self._setup_mode
            else f"Saving Face {face} and reloading masks. Cameras stay open."
        )
        self._set_busy(True, "Applying ROIs…", busy_detail)
        try:
            _save_circles(path, self.canvas.ellipses, w, h)
        except OSError as exc:
            self._set_busy(False)
            QMessageBox.critical(self, "Edit hole ROIs", f"Could not write:\n{path}\n{exc}")
            return
        cq = self._comm.get(face)
        if self._setup_mode or cq is None:
            self._set_busy(False)
            QMessageBox.information(
                self,
                "ROIs saved",
                f"Saved {len(self.canvas.ellipses)} hole(s) for Face {face}.\n"
                f"{path}\n\n"
                "Start Sequential when you are ready. Inspection will open cameras and load these holes.",
            )
            return
        try:
            cq.put({"action": "reload_rois"})
        except Exception as exc:
            self._set_busy(False)
            QMessageBox.warning(
                self,
                "Saved on disk",
                f"ROIs saved, but reload could not be sent ({exc}). "
                "Restart the app if overlays are missing. Cameras were not killed.",
            )
            return
        msg = wait_worker_event(self._snap_q, face, "reload_rois", APPLY_TIMEOUT_S)
        self._set_busy(False)
        n = len(self.canvas.ellipses)
        if not msg or not msg.get("ok"):
            QMessageBox.warning(
                self,
                "Saved on disk",
                f"Wrote {n} hole(s) to {os.path.basename(path)}.\n"
                "Worker did not confirm reload in time. Restart the app if overlays are missing. "
                "Cameras were not killed.",
            )
            return
        self._refresh_hole_combo(face)
        self.status.setText(f"Saved {n} hole(s) on Face {face}. Live overlay will update on the next frame.")
        QMessageBox.information(self, "ROIs applied", f"Saved {n} hole(s) for Face {face}. Cameras stayed live.")

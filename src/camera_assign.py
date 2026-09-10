"""
Shared camera-face assignment service.

Used by:
  - tools/assign_camera_faces.py  (CLI)
  - src/camera_setup_ui.py        (in-app PyQt wizard)

Identity model
--------------
  face        Logical manifold face (A–F). Source of truth for ROI files.
  port_path   Windows PnP InstanceId of the physical USB socket. Source of
              truth for *which camera* is that face across reboots.
  usb_index   Ephemeral OpenCV / DirectShow index used to open *right now*.

ROI files stay bound to the face (hole_positions_cam0.json = Face A), not to
the USB index. Remapping a camera to a different index must not swap ROI files.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

import cv2

from camera_indexer import (
    _get_usb_port_paths_from_registry,
    _get_wmi_camera_instance_ids_ordered,
    save_port_map,
)

VALID_FACES = ["A", "B", "C", "D", "E", "F"]
MAX_INDEX = 9
CAMERAS_JSON_FILENAME = "cameras.json"
# Face A always uses cam0 ROI file, Face B cam1, … regardless of USB index.
FACE_ROI_FILE = {face: f"hole_positions_cam{i}.json" for i, face in enumerate(VALID_FACES)}
DEFAULT_DEVICE_DESCRIPTION = "OV5693 5 MP USB Cam"


def capture_backend() -> int:
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def scan_cameras(
    max_index: int = MAX_INDEX,
    progress: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Sequentially open USB indices 0..max_index, grab one warmed snapshot, release.

    Returns list of dicts: {index, frame, width, height}.
    Only one device is held open at a time (required on shared USB hubs).
    """
    backend = capture_backend()
    found: List[Dict[str, Any]] = []

    for i in range(max_index + 1):
        if progress:
            progress(f"Opening USB index {i}…")
        cap = None
        try:
            cap = cv2.VideoCapture(i, backend)
            if not cap.isOpened():
                if progress:
                    progress(f"USB {i}: not available")
                continue

            if sys.platform == "win32":
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_FPS, 15)

            ok = False
            frame = None
            for warmup_i in range(15):
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                if warmup_i == 0:
                    time.sleep(0.4)
            if not ok or frame is None:
                if progress:
                    progress(f"USB {i}: opened but cannot read")
                continue

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or int(frame.shape[1])
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or int(frame.shape[0])
            found.append({
                "index": i,
                "frame": frame.copy(),
                "width": w,
                "height": h,
            })
            if progress:
                progress(f"USB {i}: found ({w}x{h})")
        except Exception as exc:
            if progress:
                progress(f"USB {i}: error ({exc})")
        finally:
            if cap is not None:
                cap.release()
            time.sleep(0.3)

    return found


def attach_port_paths(cameras_found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach Windows PnP InstanceId to each scanned camera (best-effort zip by index)."""
    wmi_ordered: List[str] = []
    registry: Dict[str, str] = {}
    if sys.platform == "win32":
        wmi_ordered = _get_wmi_camera_instance_ids_ordered() or []
        registry = _get_usb_port_paths_from_registry() or {}

    for cam in cameras_found:
        idx = int(cam["index"])
        if wmi_ordered and idx < len(wmi_ordered):
            path = wmi_ordered[idx]
        else:
            keys = list(registry.keys())
            path = keys[idx] if idx < len(keys) else f"UNKNOWN_PORT_{idx}"
        cam["port_path"] = path
        cam["device_description"] = registry.get(path, DEFAULT_DEVICE_DESCRIPTION)
    return cameras_found


def persist_assignments(
    config_dir: str,
    assignments: List[Dict[str, Any]],
    disable_unassigned: bool = True,
) -> Dict[str, Any]:
    """
    Write camera_port_map.json and update cameras.json.

    assignments items: {face, port_path, usb_index, device_description?}
    ROI `config` filenames stay bound to the face letter.

    Returns a summary dict for UI/CLI.
    """
    if not assignments:
        raise ValueError("No assignments to persist")

    entries = []
    for a in assignments:
        face = str(a["face"]).upper()
        entries.append({
            "face": face,
            "port_path": a.get("port_path") or f"UNKNOWN_PORT_{a['usb_index']}",
            "device_description": a.get("device_description") or DEFAULT_DEVICE_DESCRIPTION,
            "usb_index_last_seen": int(a["usb_index"]),
        })
    save_port_map(config_dir, entries)

    cameras_path = os.path.join(config_dir, CAMERAS_JSON_FILENAME)
    cameras_updated = 0
    disabled: List[str] = []
    if os.path.isfile(cameras_path):
        with open(cameras_path, "r", encoding="utf-8") as f:
            cam_data = json.load(f)

        face_to_a = {str(a["face"]).upper(): a for a in assignments}
        for cam in cam_data.get("cameras", []):
            face = str(cam.get("face", "")).upper()
            if face in face_to_a:
                a = face_to_a[face]
                cam["usb_index"] = int(a["usb_index"])
                cam["port_path"] = a.get("port_path") or cam.get("port_path")
                cam["enabled"] = True
                # Keep face-tied ROI file (A→cam0 … F→cam5). Do not rewrite to USB index.
                if not cam.get("config"):
                    cam["config"] = FACE_ROI_FILE.get(face, "hole_positions_cam0.json")
                cameras_updated += 1
            elif disable_unassigned:
                if cam.get("enabled", True):
                    disabled.append(face)
                cam["enabled"] = False

        with open(cameras_path, "w", encoding="utf-8") as f:
            json.dump(cam_data, f, indent=2)
            f.write("\n")

    return {
        "port_map_path": os.path.join(config_dir, "camera_port_map.json"),
        "cameras_path": cameras_path,
        "assigned": [str(a["face"]).upper() for a in assignments],
        "cameras_updated": cameras_updated,
        "disabled": disabled,
    }

#!/usr/bin/env python3
"""
Camera Diagnostic Tool

Checks all USB indices to find available cameras and their capabilities.
On Windows: also displays the stable USB port-path for each camera and
cross-references against config/camera_port_map.json if it exists.

Usage (from repo root):
    python diagnose_cameras.py
"""

import cv2
import sys
import os
import json

# ── Path setup for camera_indexer ─────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from camera_indexer import _get_wmi_camera_instance_ids_ordered, load_port_map
    _INDEXER_AVAILABLE = True
except ImportError:
    _INDEXER_AVAILABLE = False


# ── Platform-specific backend ─────────────────────────────────────────────────
if sys.platform == "darwin":
    BACKEND = cv2.CAP_AVFOUNDATION
    BACKEND_NAME = "AVFoundation"
elif sys.platform == "win32":
    BACKEND = cv2.CAP_DSHOW   # DirectShow — consistent index order on Windows
    BACKEND_NAME = "DirectShow (CAP_DSHOW)"
else:
    BACKEND = cv2.CAP_V4L2
    BACKEND_NAME = "V4L2"


def check_camera(index):
    """Check if a camera is available at the given index. Returns info dict or None."""
    cap = cv2.VideoCapture(index, BACKEND)
    if not cap.isOpened():
        return None

    width  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps    = cap.get(cv2.CAP_PROP_FPS)
    ret, _ = cap.read()
    cap.release()

    return {
        "index": index,
        "resolution": f"{width}x{height}",
        "fps": fps,
        "can_read": ret,
    }


def load_port_map_safe(config_dir):
    """Load camera_port_map.json without crashing if absent."""
    if not _INDEXER_AVAILABLE:
        return {}
    entries = load_port_map(config_dir)
    if not entries:
        return {}
    # Build {port_path -> face} for quick lookup
    return {str(e.get("port_path", "")).upper(): e.get("face", "?") for e in entries}


def main():
    # Resolve config dir (repo root / config)
    config_dir = os.path.join(SCRIPT_DIR, "config")

    print("=" * 70)
    print("  CAMERA DIAGNOSTIC TOOL")
    print("=" * 70)
    print(f"  Backend  : {BACKEND_NAME}")
    print(f"  Platform : {sys.platform}")
    print(f"  Config   : {config_dir}")
    print()

    # ── Get WMI port paths (Windows only) ─────────────────────────────────────
    wmi_paths = []
    if sys.platform == "win32" and _INDEXER_AVAILABLE:
        print("Reading USB port paths (WMI)...")
        wmi_paths = _get_wmi_camera_instance_ids_ordered()
        if wmi_paths:
            print(f"  WMI found {len(wmi_paths)} UVC camera device(s).")
        else:
            print("  WMI returned no camera devices (wmi package may not be installed).")
        print()

    # ── Load saved port map for cross-reference ────────────────────────────────
    port_map = load_port_map_safe(config_dir)
    has_port_map = bool(port_map)

    # ── Scan camera indices ────────────────────────────────────────────────────
    print(f"Scanning USB indices 0–9 using {BACKEND_NAME}...")
    print()

    available = []
    for i in range(10):
        result = check_camera(i)
        if result is None:
            print(f"  USB {i:>2}: NOT AVAILABLE")
            continue

        status = "CAN READ" if result["can_read"] else "NO READ"

        # Get port path for this index
        port_path = wmi_paths[i] if (wmi_paths and i < len(wmi_paths)) else ""

        # Cross-reference with saved port map
        face_assignment = ""
        if port_path and has_port_map:
            face_assignment = port_map.get(port_path.upper(), "UNKNOWN")
            face_label = f"  =>  Face {face_assignment}" if face_assignment else "  =>  (not in port map)"
        elif not has_port_map:
            face_label = "  (no port map — run: python tools/assign_camera_faces.py)"
        else:
            face_label = ""

        line = f"  USB {i:>2}: {result['resolution']} @ {result['fps']:.0f}fps  [{status}]"
        if port_path:
            line += f"\n          Port: {port_path}{face_label}"
        else:
            line += face_label

        print(line)
        available.append(result)
        print()

    # ── Summary ────────────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"  SUMMARY: Found {len(available)} camera(s)")
    print("=" * 70)

    if available:
        indices = [c["index"] for c in available]
        print(f"  Working indices: {indices}")
        print()
        if not has_port_map:
            print("  ACTION REQUIRED: Run the face assignment wizard before using the system:")
            print("      python tools/assign_camera_faces.py")
        else:
            print("  camera_port_map.json is present. Face assignments cross-referenced above.")
            print("  If any face shows UNKNOWN, re-run: python tools/assign_camera_faces.py")
    else:
        print("  No cameras found! Check USB connections and permissions.")

    print()


if __name__ == "__main__":
    main()

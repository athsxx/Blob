"""
assign_camera_faces.py — One-Time Camera Face Assignment Wizard

Run this ONCE after physically mounting your cameras, or whenever you
re-cable cameras to different USB ports.

Usage (from repo root):
    python tools/assign_camera_faces.py
    python tools/assign_camera_faces.py --config-dir path/to/config

What it does
------------
1. Scans all USB camera indices (0-9)
2. For each found camera: opens a window showing a live snapshot
3. Operator types which manifold face (A-F) that camera is watching
4. Saves the USB port-path -> face mapping to config/camera_port_map.json
5. Also updates config/cameras.json with the correct usb_index ordering

After running this wizard, src/main.py will automatically resolve
camera indices correctly at every boot, even after reboots or USB hub changes.

Windows requirement: pip install wmi  (already in requirements.txt)
"""

import sys
import os
import json
import cv2
import time
from typing import Dict, List, Optional, Any

# ── Path setup ────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT   = os.path.dirname(SCRIPT_DIR)
SRC_DIR     = os.path.join(REPO_ROOT, "src")
sys.path.insert(0, SRC_DIR)

from camera_indexer import (
    _get_wmi_camera_instance_ids_ordered,
    _get_usb_port_paths_from_registry,
    save_port_map,
    PORT_MAP_SCHEMA_VERSION,
)

# ── Config ────────────────────────────────────────────────────────────────────
VALID_FACES = ["A", "B", "C", "D", "E", "F"]
MAX_INDEX   = 9
CAMERAS_JSON_FILENAME = "cameras.json"

if sys.platform == "win32":
    BACKEND = cv2.CAP_DSHOW
elif sys.platform == "darwin":
    BACKEND = cv2.CAP_AVFOUNDATION
else:
    BACKEND = cv2.CAP_ANY


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def scan_cameras(max_index: int = MAX_INDEX) -> List[Dict[str, Any]]:
    """
    Scan USB indices 0..max_index and return info for each working camera.
    Returns list of dicts: {index, frame, width, height}
    """
    found = []
    print(f"\nScanning camera indices 0–{max_index}...")

    for i in range(max_index + 1):
        print(f"  Checking index {i}...", end="", flush=True)
        cap = None
        try:
            cap = cv2.VideoCapture(i, BACKEND)
            if not cap.isOpened():
                print(" not available.")
                continue

            # Warm up — Windows UVC cameras need more frames for AGC/exposure to settle.
            # Discard first 15 frames; use the 16th as the actual snapshot.
            ok = False
            for warmup_i in range(15):
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                # Extra settle after first successful read on Windows USB buses
                if warmup_i == 0:
                    time.sleep(0.5)

            if not ok:
                print(" opened but cannot read frame.")
                cap.release()
                continue

            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f" FOUND ({w}x{h})")
            found.append({"index": i, "frame": frame.copy(), "width": w, "height": h})

        except Exception as e:
            print(f" error: {e}")
        finally:
            if cap is not None:
                cap.release()
            time.sleep(0.3)  # brief settle between opens

    return found


def get_port_path_for_index(cv_index: int) -> str:
    """
    Get the stable USB port-path string for a given OpenCV camera index.
    Uses WMI if available, otherwise falls back to registry.
    Returns empty string if unavailable (non-Windows).
    """
    if sys.platform != "win32":
        return ""

    # WMI gives us ordered list matching DirectShow indices
    wmi_ordered = _get_wmi_camera_instance_ids_ordered()
    if wmi_ordered and cv_index < len(wmi_ordered):
        return wmi_ordered[cv_index]

    # Fallback: registry scan (unordered, best-effort)
    registry_paths = _get_usb_port_paths_from_registry()
    devices = list(registry_paths.keys())
    if cv_index < len(devices):
        return devices[cv_index]

    return f"UNKNOWN_PORT_{cv_index}"


def show_camera_window(cam_info: Dict[str, Any]) -> None:
    """Display the camera snapshot in an OpenCV window."""
    frame = cam_info["frame"].copy()
    idx = cam_info["index"]

    # Draw label overlay
    label = f"Camera Index: {idx}  |  {cam_info['width']}x{cam_info['height']}"
    cv2.putText(
        frame, label, (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4
    )
    cv2.putText(
        frame, label, (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2
    )

    instruction = "Look at the camera's live view, then type the face (A-F) in the terminal."
    cv2.putText(
        frame, instruction, (20, frame.shape[0] - 30),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3
    )
    cv2.putText(
        frame, instruction, (20, frame.shape[0] - 30),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 255), 1
    )

    win_name = f"Camera {idx} — Assign Face"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, min(cam_info["width"] * 2, 1280), min(cam_info["height"] * 2, 960))
    cv2.imshow(win_name, frame)
    cv2.waitKey(1)  # Render without blocking


def close_camera_window(idx: int) -> None:
    win_name = f"Camera {idx} — Assign Face"
    try:
        cv2.destroyWindow(win_name)
    except Exception:
        pass


def prompt_face_assignment(cam_info: Dict[str, Any], already_assigned: List[str]) -> Optional[str]:
    """
    Show the camera snapshot and ask the operator to type the face letter.
    Returns uppercase face letter or None if skipped.
    """
    idx = cam_info["index"]
    remaining = [f for f in VALID_FACES if f not in already_assigned]

    show_camera_window(cam_info)

    print(f"\n{'='*60}")
    print(f"  Camera at USB index {idx}  ({cam_info['width']}x{cam_info['height']})")
    print(f"  A window is showing this camera's image.")
    print(f"  Remaining unassigned faces: {', '.join(remaining)}")
    print(f"{'='*60}")

    while True:
        raw = input("  Which manifold face does this camera watch? (A-F, or 's' to skip): ").strip().upper()
        if raw == "S":
            close_camera_window(idx)
            return None
        if raw in VALID_FACES:
            if raw in already_assigned:
                print(f"  ERROR: Face {raw} is already assigned. Choose another.")
                continue
            close_camera_window(idx)
            return raw
        print(f"  Invalid input. Enter one of: {', '.join(VALID_FACES)}, or 's' to skip.")


def update_cameras_json(config_dir: str, assignments: List[Dict[str, Any]]) -> None:
    """
    Update config/cameras.json so that each face entry has the correct usb_index
    from this assignment session.
    """
    cameras_path = os.path.join(config_dir, CAMERAS_JSON_FILENAME)
    if not os.path.isfile(cameras_path):
        print(f"\n[Wizard] cameras.json not found at {cameras_path} -- skipping cameras.json update.")
        return

    try:
        with open(cameras_path, "r", encoding="utf-8") as f:
            cam_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"\n[Wizard] Could not read cameras.json: {e}")
        return

    # Build face -> usb_index map from assignment session
    face_to_index: Dict[str, int] = {
        a["face"]: a["usb_index_at_assignment"] for a in assignments
    }

    updated = 0
    for cam in cam_data.get("cameras", []):
        face = str(cam.get("face", "")).upper()
        if face in face_to_index:
            old_idx = cam.get("usb_index", "?")
            new_idx = face_to_index[face]
            if old_idx != new_idx:
                cam["usb_index"] = new_idx
                cam["config"] = f"hole_positions_cam{new_idx}.json"
                updated += 1
                print(f"  [cameras.json] Face {face}: usb_index {old_idx} -> {new_idx}")
            # Also store port_path for reference (optional field)
            for a in assignments:
                if a["face"] == face:
                    cam["port_path"] = a["port_path"]
                    break

    with open(cameras_path, "w", encoding="utf-8") as f:
        json.dump(cam_data, f, indent=2)

    if updated:
        print(f"  [cameras.json] Updated {updated} camera(s) with new USB indices.")
    else:
        print("  [cameras.json] No changes needed (indices already match).")


# ──────────────────────────────────────────────────────────────────────────────
# Main wizard flow
# ──────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Camera Face Assignment Wizard")
    default_config = os.path.join(REPO_ROOT, "config")
    parser.add_argument(
        "--config-dir", default=default_config,
        help=f"Path to config directory (default: {default_config})"
    )
    parser.add_argument(
        "--max-index", type=int, default=MAX_INDEX,
        help=f"Maximum USB index to scan (default: {MAX_INDEX})"
    )
    args = parser.parse_args()
    config_dir = os.path.abspath(args.config_dir)

    print("=" * 60)
    print("  MANIFOLD INSPECTION — CAMERA FACE ASSIGNMENT WIZARD")
    print("=" * 60)
    print()
    print("This tool maps each physical camera to a manifold face (A-F).")
    print("Run this ONCE after mounting cameras, or after re-cabling.")
    print()
    print(f"Config directory : {config_dir}")
    print(f"Platform         : {sys.platform}")
    print(f"OpenCV backend   : {'CAP_DSHOW' if BACKEND == cv2.CAP_DSHOW else str(BACKEND)}")
    print()

    # Check for existing port map and warn
    port_map_path = os.path.join(config_dir, "camera_port_map.json")
    if os.path.isfile(port_map_path):
        print("WARNING: camera_port_map.json already exists and will be OVERWRITTEN.")
        confirm = input("Continue? (y/N): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return
        print()

    # Step 1: Scan cameras
    cameras_found = scan_cameras(max_index=args.max_index)

    if not cameras_found:
        print("\nERROR: No cameras found. Check USB connections and try again.")
        return

    print(f"\nFound {len(cameras_found)} camera(s): indices {[c['index'] for c in cameras_found]}")
    print()

    # Step 2: Get port paths (Windows only)
    print("Reading USB port paths from Windows registry/WMI...")
    port_paths: Dict[int, str] = {}
    if sys.platform == "win32":
        wmi_list = _get_wmi_camera_instance_ids_ordered()
        for cam in cameras_found:
            idx = cam["index"]
            if wmi_list and idx < len(wmi_list):
                port_paths[idx] = wmi_list[idx]
            else:
                port_paths[idx] = get_port_path_for_index(idx)
            print(f"  USB {idx}: {port_paths.get(idx, 'UNKNOWN')}")
    else:
        print("  (Non-Windows: port paths not available — assignment will use index only)")
    print()

    # Step 3: Assign faces interactively
    print("For each camera, a window will show the live image.")
    print("Look at what manifold face the camera is watching and type the letter.")
    print()
    input("Press Enter to start the assignment process...")
    print()

    assignments: List[Dict[str, Any]] = []
    already_assigned: List[str] = []

    for cam_info in cameras_found:
        idx = cam_info["index"]
        port_path = port_paths.get(idx, f"UNKNOWN_PORT_{idx}")

        face = prompt_face_assignment(cam_info, already_assigned)

        if face is None:
            print(f"  Skipped camera at index {idx}.")
            continue

        already_assigned.append(face)
        assignments.append({
            "face": face,
            "port_path": port_path,
            "device_description": "OV2064 USB Camera",
            "usb_index_at_assignment": idx,
            "usb_index_last_seen": idx,
        })
        print(f"  Assigned: Face {face} -> USB index {idx}")

    cv2.destroyAllWindows()

    if not assignments:
        print("\nNo assignments made. Exiting without saving.")
        return

    # Step 4: Review
    print()
    print("=" * 60)
    print("  ASSIGNMENT SUMMARY")
    print("=" * 60)
    print(f"  {'Face':<6} {'USB Index':<10} {'Port Path'}")
    print(f"  {'----':<6} {'─────────':<10} {'─────────────────────────────────────────'}")
    for a in sorted(assignments, key=lambda x: x["face"]):
        print(f"  {a['face']:<6} {a['usb_index_at_assignment']:<10} {a['port_path']}")

    missing = [f for f in VALID_FACES if f not in [a["face"] for a in assignments]]
    if missing:
        print(f"\n  WARNING: Unassigned faces: {', '.join(missing)}")
        print("  You can disable these faces in config/cameras.json (enabled: false)")

    print()
    confirm = input("Save this assignment? (Y/n): ").strip().lower()
    if confirm == "n":
        print("Aborted. No files written.")
        return

    # Step 5: Save port map
    port_map_entries = [
        {
            "face": a["face"],
            "port_path": a["port_path"],
            "device_description": a["device_description"],
            "usb_index_last_seen": a["usb_index_last_seen"],
        }
        for a in assignments
    ]
    save_port_map(config_dir, port_map_entries)
    print(f"\n[Wizard] Saved: {port_map_path}")

    # Step 6: Update cameras.json
    print("[Wizard] Updating cameras.json...")
    update_cameras_json(config_dir, assignments)

    print()
    print("=" * 60)
    print("  ASSIGNMENT COMPLETE")
    print("=" * 60)
    print()
    print("  camera_port_map.json has been written.")
    print("  The inspection system will now resolve camera indices")
    print("  automatically at every startup.")
    print()
    print("  Next steps:")
    print("    1. Verify with: python diagnose_cameras.py")
    print("    2. Calibrate ROIs if not already done: python calibrate.py --cam N")
    print("    3. Run the system: python src/main.py")
    print()


if __name__ == "__main__":
    main()

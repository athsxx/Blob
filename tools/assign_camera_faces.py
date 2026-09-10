"""
assign_camera_faces.py — CLI camera-face assignment wizard

Run once after mounting cameras, or after re-cabling USB ports.

    python tools/assign_camera_faces.py
    python tools/assign_camera_faces.py --config-dir path/to/config

The same persist path is used by the in-app wizard (Assign camera faces).
"""

import sys
import os
import cv2
from typing import Any, Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SRC_DIR = os.path.join(REPO_ROOT, "src")
sys.path.insert(0, SRC_DIR)

from camera_assign import (  # noqa: E402
    VALID_FACES,
    MAX_INDEX,
    attach_port_paths,
    capture_backend,
    persist_assignments,
    scan_cameras,
)


def show_camera_window(cam_info: Dict[str, Any]) -> None:
    frame = cam_info["frame"].copy()
    idx = cam_info["index"]
    label = f"Camera Index: {idx}  |  {cam_info['width']}x{cam_info['height']}"
    cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 4)
    cv2.putText(frame, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    instruction = "Look at this view, then type the face (A-F) in the terminal."
    cv2.putText(frame, instruction, (20, frame.shape[0] - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
    cv2.putText(frame, instruction, (20, frame.shape[0] - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 255), 1)
    win_name = f"Camera {idx} — Assign Face"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, min(cam_info["width"] * 2, 1280), min(cam_info["height"] * 2, 960))
    cv2.imshow(win_name, frame)
    cv2.waitKey(1)


def close_camera_window(idx: int) -> None:
    try:
        cv2.destroyWindow(f"Camera {idx} — Assign Face")
    except Exception:
        pass


def prompt_face_assignment(cam_info: Dict[str, Any], already_assigned: List[str]) -> Optional[str]:
    idx = cam_info["index"]
    remaining = [f for f in VALID_FACES if f not in already_assigned]
    show_camera_window(cam_info)
    print(f"\n{'=' * 60}")
    print(f"  Camera at USB index {idx}  ({cam_info['width']}x{cam_info['height']})")
    print(f"  Remaining unassigned faces: {', '.join(remaining)}")
    print(f"{'=' * 60}")
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


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Camera Face Assignment Wizard")
    parser.add_argument("--config-dir", default=os.path.join(REPO_ROOT, "config"))
    parser.add_argument("--max-index", type=int, default=MAX_INDEX)
    args = parser.parse_args()
    config_dir = os.path.abspath(args.config_dir)
    backend = capture_backend()

    print("=" * 60)
    print("  MANIFOLD INSPECTION — CAMERA FACE ASSIGNMENT WIZARD")
    print("=" * 60)
    print()
    print("Maps each physical camera to a manifold face (A-F).")
    print("The in-app wizard (Assign camera faces) does the same thing from the dashboard.")
    print()
    print(f"Config directory : {config_dir}")
    print(f"Platform         : {sys.platform}")
    print(f"OpenCV backend   : {backend}")
    print()

    port_map_path = os.path.join(config_dir, "camera_port_map.json")
    if os.path.isfile(port_map_path):
        print("WARNING: camera_port_map.json already exists and will be OVERWRITTEN.")
        if input("Continue? (y/N): ").strip().lower() != "y":
            print("Aborted.")
            return
        print()

    cameras_found = scan_cameras(max_index=args.max_index, progress=print)
    if not cameras_found:
        print("\nERROR: No cameras found. Check USB connections and try again.")
        return

    attach_port_paths(cameras_found)
    print(f"\nFound {len(cameras_found)} camera(s): indices {[c['index'] for c in cameras_found]}")
    for cam in cameras_found:
        print(f"  USB {cam['index']}: {cam.get('port_path', 'UNKNOWN')}")
    print()
    input("Press Enter to start the assignment process...")
    print()

    assignments: List[Dict[str, Any]] = []
    already_assigned: List[str] = []
    for cam_info in cameras_found:
        face = prompt_face_assignment(cam_info, already_assigned)
        if face is None:
            print(f"  Skipped camera at index {cam_info['index']}.")
            continue
        already_assigned.append(face)
        assignments.append({
            "face": face,
            "port_path": cam_info.get("port_path", f"UNKNOWN_PORT_{cam_info['index']}"),
            "device_description": cam_info.get("device_description"),
            "usb_index": cam_info["index"],
        })
        print(f"  Assigned: Face {face} -> USB index {cam_info['index']}")

    cv2.destroyAllWindows()
    if not assignments:
        print("\nNo assignments made. Exiting without saving.")
        return

    print()
    print("=" * 60)
    print("  ASSIGNMENT SUMMARY")
    print("=" * 60)
    print(f"  {'Face':<6} {'USB Index':<10} {'Port Path'}")
    for a in sorted(assignments, key=lambda x: x["face"]):
        print(f"  {a['face']:<6} {a['usb_index']:<10} {a['port_path']}")
    missing = [f for f in VALID_FACES if f not in [a["face"] for a in assignments]]
    if missing:
        print(f"\n  Unassigned faces will be disabled: {', '.join(missing)}")
    print()
    if input("Save this assignment? (Y/n): ").strip().lower() == "n":
        print("Aborted. No files written.")
        return

    summary = persist_assignments(config_dir, assignments, disable_unassigned=True)
    print(f"\n[Wizard] Saved: {summary['port_map_path']}")
    if summary["disabled"]:
        print(f"[Wizard] Disabled faces with no camera: {', '.join(summary['disabled'])}")
    print()
    print("  Next: python diagnose_cameras.py   then   python src/main.py")
    print()


if __name__ == "__main__":
    main()

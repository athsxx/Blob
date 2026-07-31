"""
Run this once, with all 6 OV5640 cameras plugged into their assigned
physical ports, to capture each camera's DirectShow device path.

Since these cameras likely share identical VID/PID (and possibly
identical/duplicate serials), the goal here is NOT to compare VID/PID —
it's to record the FULL path string per camera and check whether the
port/hub location shows up as a distinguishing fragment.

Usage:
    python enumerate_cameras.py
"""

from pyusbcameraindex import enumerate_usb_video_devices_windows
import cv2
import json
import os

OUTPUT_FILE = "camera_paths_raw.json"


def main():
    devices = enumerate_usb_video_devices_windows()

    if not devices:
        print("No USB video devices found. Check connections and drivers.")
        return

    print(f"Found {len(devices)} camera(s).\n")

    records = []
    for d in devices:
        record = {
            "index": d.index,
            "name": d.name,
            "vid": d.vid,
            "pid": d.pid,
            "path": d.path,
        }
        records.append(record)
        print(f"Index: {d.index}")
        print(f"  Name: {d.name}")
        print(f"  VID:  {d.vid}")
        print(f"  PID:  {d.pid}")
        print(f"  Path: {d.path}")
        print()

    # Check whether VID/PID are identical across all devices (expected for OV5640 clones)
    vid_pid_pairs = {(r["vid"], r["pid"]) for r in records}
    if len(vid_pid_pairs) == 1 and len(records) > 1:
        print("NOTE: All cameras share the same VID/PID, as expected for identical")
        print("OV5640 modules. Identity must come from the 'path' field instead.\n")

    # Check whether paths are all unique (they need to be, for port-based mapping to work)
    paths = [r["path"] for r in records]
    if len(set(paths)) == len(paths):
        print("GOOD: All device paths are unique. Port-based mapping will work.\n")
    else:
        print("WARNING: Some device paths are identical! Port-based mapping will")
        print("NOT reliably distinguish these cameras. A physical marker-based")
        print("calibration step (e.g. AprilTag per camera) will be needed instead.\n")

    with open(OUTPUT_FILE, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Raw enumeration saved to {OUTPUT_FILE}")
    print("\nNext: open each camera by index below and confirm visually which")
    print("physical port/face each index corresponds to, one at a time.")

    # Optional visual confirmation: opens each camera briefly so you can
    # match index -> physical camera by sight.
    confirm = input("\nOpen each camera one-by-one to visually confirm? (y/n): ")
    if confirm.lower() == "y":
        for r in records:
            print(f"\nOpening index {r['index']} ({r['name']})... press any key to close.")
            cap = cv2.VideoCapture(r["index"], cv2.CAP_DSHOW)
            ret, frame = cap.read()
            if ret:
                cv2.imshow(f"Index {r['index']}", frame)
                cv2.waitKey(0)
                cv2.destroyAllWindows()
            else:
                print(f"  Could not read frame from index {r['index']}.")
            cap.release()


if __name__ == "__main__":
    main()

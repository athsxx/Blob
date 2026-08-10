import cv2
import sys
import os

# ── Path setup ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(SCRIPT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

try:
    from camera_indexer import _get_wmi_camera_instance_ids_ordered
    _INDEXER_AVAILABLE = True
except ImportError:
    _INDEXER_AVAILABLE = False

# Use CAP_DSHOW on Windows — same index order as WMI / DirectShow enumeration.
# CAP_ANY on Windows is non-deterministic after reboots.
if sys.platform == "darwin":
    BACKEND = cv2.CAP_AVFOUNDATION
elif sys.platform == "win32":
    BACKEND = cv2.CAP_DSHOW
else:
    BACKEND = cv2.CAP_ANY

def capture_and_label_cameras():
    print("=" * 60)
    print("CAMERA INDEX IDENTIFICATION TOOL")
    print("=" * 60)

    backend_name = (
        "AVFoundation" if sys.platform == "darwin"
        else "CAP_DSHOW" if sys.platform == "win32"
        else "CAP_ANY"
    )
    print(f"Platform: {sys.platform}  |  Backend: {backend_name}")
    print()

    # Get WMI port paths for overlay (Windows only)
    wmi_paths = []
    if sys.platform == "win32" and _INDEXER_AVAILABLE:
        print("Reading USB port paths from WMI...")
        wmi_paths = _get_wmi_camera_instance_ids_ordered()
        print(f"  {len(wmi_paths)} UVC device(s) found via WMI.")
    print()

    # Create output directory
    output_dir = "camera_indices_check"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    found_cameras = []

    # Check indices 0-9
    for i in range(10):
        print(f"Checking index {i}...", end="", flush=True)
        cap = None
        try:
            cap = cv2.VideoCapture(i, BACKEND)

            if not cap.isOpened():
                print(" Not available.")
                continue

            # Try to read a frame
            ret, frame = cap.read()

            if ret:
                height, width = frame.shape[:2]

                # Line 1: index + resolution
                line1 = f"Camera Index: {i}   {width}x{height}"
                # Line 2: port path (if available)
                port_path = wmi_paths[i] if (wmi_paths and i < len(wmi_paths)) else ""
                line2 = port_path if port_path else "(port path unavailable)"

                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 1.2
                thickness = 2

                for line_num, text in enumerate([line1, line2]):
                    (tw, th), bl = cv2.getTextSize(text, font, font_scale, thickness)
                    y = 60 + line_num * (th + 20)
                    # Background rect
                    cv2.rectangle(frame, (40, y - th - 10), (40 + tw + 20, y + bl + 10), (0, 0, 0), -1)
                    cv2.putText(frame, text, (50, y), font, font_scale, (0, 255, 0), thickness)

                filename = os.path.join(output_dir, f"camera_index_{i}.jpg")
                cv2.imwrite(filename, frame)
                print(f" CAPTURED -> {filename}")
                if port_path:
                    print(f"           Port: {port_path}")
                found_cameras.append(i)
            else:
                print(" Opened but failed to read frame.")
        except Exception as e:
            print(f" Error: {e}")
        finally:
            if cap is not None:
                cap.release()

    print("-" * 60)
    if found_cameras:
        print(f"Captured images for indices: {found_cameras}")
        print(f"Check the '{output_dir}/' folder to match physical cameras to indices.")
        print()
        print("Next step: run the face assignment wizard:")
        print("    python tools/assign_camera_faces.py")

        if sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", output_dir], check=False)
        elif sys.platform == "win32":
            import subprocess
            subprocess.run(["explorer", output_dir], check=False)
    else:
        print("No cameras could be read.")
    print("=" * 60)


if __name__ == "__main__":
    capture_and_label_cameras()


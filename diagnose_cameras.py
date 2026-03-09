#!/usr/bin/env python3
"""
Camera Diagnostic Tool
Checks all USB indices to find available cameras and their capabilities.
"""

import cv2
import sys

def check_camera(index, backend=None):
    if backend is None:
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else (cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY)
    """Check if a camera is available at the given index."""
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        return None
    
    # Get camera properties
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    
    # Try to read a frame
    ret, _ = cap.read()
    can_read = ret
    
    cap.release()
    
    return {
        "index": index,
        "resolution": f"{width}x{height}",
        "fps": fps,
        "can_read": can_read
    }

def main():
    print("=" * 60)
    print("CAMERA DIAGNOSTIC TOOL")
    print("=" * 60)
    print()
    
    backend_name = "AVFoundation" if sys.platform == "darwin" else "Default"
    backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
    
    print(f"Backend: {backend_name}")
    print(f"Checking USB indices 0-9...")
    print()
    
    available = []
    for i in range(10):
        result = check_camera(i, backend)
        if result:
            status = "✓ CAN READ" if result["can_read"] else "✗ NO READ"
            print(f"  USB {i}: {result['resolution']} @ {result['fps']:.0f}fps  [{status}]")
            available.append(result)
        else:
            print(f"  USB {i}: NOT AVAILABLE")
    
    print()
    print("=" * 60)
    print(f"SUMMARY: Found {len(available)} cameras")
    print("=" * 60)
    
    if available:
        print("\nAvailable camera indices:", [c["index"] for c in available])
        print("\nUpdate your config/cameras.json to use these indices.")
    else:
        print("\nNo cameras found! Check USB connections and permissions.")

if __name__ == "__main__":
    main()

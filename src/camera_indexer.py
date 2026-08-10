"""
camera_indexer.py — Deterministic Camera-Face Resolver (Windows USB Port-Path Fingerprinting)

Problem solved
--------------
Windows assigns USB camera indices (0, 1, 2 …) non-deterministically after reboots,
hub swaps, or USB re-plugging. Because all six OV2064 cameras are identical devices,
OpenCV cannot distinguish them by name or serial number. This module uses the
*physical USB port path* stored in the Windows registry to pin each camera to its
manifold face, regardless of which integer index Windows assigns at runtime.

How it works
------------
1. On first use, the operator runs `tools/assign_camera_faces.py` which saves
   a `config/camera_port_map.json` file:  face -> { port_path, usb_index_last_seen }

2. At every startup this module:
   a. Reads camera_port_map.json
   b. Tries the cached usb_index_last_seen for each face (fast path -- 0ms overhead)
   c. If the cached index now has a different port_path (camera moved), does a full
      re-enumeration scan to find the correct index (slow path -- ~2s per camera)
   d. Updates the in-memory cameras list with resolved usb_index values
   e. Writes updated cache back to camera_port_map.json

Non-Windows behaviour
---------------------
The module is a safe no-op on macOS/Linux -- it returns the cameras list unchanged.

Port map schema (config/camera_port_map.json)
---------------------------------------------
{
  "schema_version": 1,
  "entries": [
    {
      "face": "A",
      "port_path": "USB\\VID_05A3&PID_9230\\5&1A2B3C4D&0&1",
      "device_description": "USB Camera",
      "usb_index_last_seen": 0
    },
    ...
  ]
}
"""

import sys
import os
import json
import time
import cv2
from typing import Dict, List, Optional, Tuple, Any

PORT_MAP_FILENAME = "camera_port_map.json"
PORT_MAP_SCHEMA_VERSION = 1

# ──────────────────────────────────────────────────────────────────────────────
# Registry helpers (Windows only)
# ──────────────────────────────────────────────────────────────────────────────

def _get_usb_port_paths_from_registry() -> Dict[str, str]:
    """
    Enumerate USB camera devices from the Windows registry.

    Returns a dict mapping DeviceInstanceId -> friendly_description for
    all UVC-class devices found under
    HKLM\\SYSTEM\\CurrentControlSet\\Enum\\USB

    Only available on Windows; returns {} on other platforms or on error.
    """
    if sys.platform != "win32":
        return {}

    try:
        import winreg  # built-in on Windows, no pip needed
    except ImportError:
        print("[CameraIndexer] WARNING: winreg not available -- cannot read USB port paths.")
        return {}

    result: Dict[str, str] = {}
    USB_ROOT = r"SYSTEM\CurrentControlSet\Enum\USB"

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, USB_ROOT) as usb_key:
            vid_pid_count = winreg.QueryInfoKey(usb_key)[0]
            for i in range(vid_pid_count):
                try:
                    vid_pid = winreg.EnumKey(usb_key, i)
                    vid_pid_path = f"{USB_ROOT}\\{vid_pid}"
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, vid_pid_path) as vp_key:
                        instance_count = winreg.QueryInfoKey(vp_key)[0]
                        for j in range(instance_count):
                            try:
                                instance_id = winreg.EnumKey(vp_key, j)
                                inst_path = f"{vid_pid_path}\\{instance_id}"
                                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, inst_path) as inst_key:
                                    try:
                                        class_val, _ = winreg.QueryValueEx(inst_key, "Class")
                                    except FileNotFoundError:
                                        class_val = ""
                                    if str(class_val).lower() not in ("camera", "image", "media"):
                                        continue
                                    device_instance_id = f"USB\\{vid_pid}\\{instance_id}"
                                    try:
                                        desc, _ = winreg.QueryValueEx(inst_key, "DeviceDesc")
                                    except FileNotFoundError:
                                        desc = "USB Camera"
                                    result[device_instance_id] = str(desc)
                            except OSError:
                                continue
                except OSError:
                    continue
    except OSError as e:
        print(f"[CameraIndexer] WARNING: Failed to read USB registry key: {e}")

    return result


def _get_wmi_camera_instance_ids_ordered() -> List[str]:
    """
    Get UVC camera instance IDs in DirectShow enumeration order (index 0, 1, 2...).

    Uses PowerShell Get-PnpDevice first — this returns devices in the SAME order
    that DirectShow (and therefore OpenCV CAP_DSHOW) assigns indices.

    Falls back to WMI Win32_PnPEntity if PowerShell is unavailable.
    Returns [] on non-Windows or on all errors.
    """
    if sys.platform != "win32":
        return []

    # ── Primary: PowerShell Get-PnpDevice (authoritative DShow order) ──────────
    try:
        import subprocess
        import json as _json

        ps_cmd = (
            "Get-PnpDevice -Class Camera -Status OK | "
            "Sort-Object InstanceId | "
            "Select-Object -ExpandProperty InstanceId | "
            "ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = result.stdout.strip()
            parsed = _json.loads(raw)
            if isinstance(parsed, str):
                # Single device — PowerShell returns a bare string, not a list
                return [parsed]
            if isinstance(parsed, list):
                return [str(x) for x in parsed if x]
    except Exception as e:
        print(f"[CameraIndexer] PowerShell Get-PnpDevice failed: {e} — trying WMI fallback")

    # ── Fallback: WMI Win32_PnPEntity ──────────────────────────────────────────
    # NOTE: WMI ordering may differ from DShow order in rare cases.
    # If both PowerShell and WMI fail, index resolution falls back to open-and-verify.
    try:
        import wmi  # type: ignore[import]
    except ImportError:
        return []

    try:
        c = wmi.WMI()
        devices = []
        for pnp in c.Win32_PnPEntity():
            if pnp.PNPClass and str(pnp.PNPClass).lower() in ("camera", "image"):
                devices.append(pnp.DeviceID or "")
        return devices
    except Exception as e:
        print(f"[CameraIndexer] WMI query also failed: {e}")
        return []


def _enumerate_cv_index_to_port_path(
    max_index: int = 9,
    backend: int = cv2.CAP_DSHOW,
) -> Dict[int, str]:
    """
    Build a mapping of { usb_index -> registry_port_path } for all currently
    accessible cameras on Windows.

    Uses WMI to get the ordered list of UVC cameras and cross-references with
    OpenCV's enumeration order under DirectShow.

    Falls back to marking indices as UNKNOWN if WMI unavailable.
    """
    if sys.platform != "win32":
        return {}

    # Step 1: Get WMI ordered camera list (same order as DShow indices)
    wmi_paths = _get_wmi_camera_instance_ids_ordered()
    if wmi_paths:
        return {i: path for i, path in enumerate(wmi_paths)}

    # Step 2: Fallback -- open each index, mark as unmatched
    result: Dict[int, str] = {}
    for idx in range(max_index + 1):
        try:
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            ok, _ = cap.read()
            cap.release()
            if ok:
                result[idx] = f"UNKNOWN_CAM_{idx}"
        except Exception:
            continue

    return result


def _verify_index_port_path(
    usb_index: int,
    expected_port_path: str,
    backend: int = cv2.CAP_DSHOW,
) -> bool:
    """
    Fast check: verify that usb_index currently corresponds to expected_port_path.

    Uses WMI ordered list (no camera open needed).
    Falls back to opening the camera if WMI unavailable.
    Returns True if confirmed correct, False if stale.
    """
    if sys.platform != "win32":
        return True  # Can't verify; assume correct on non-Windows

    wmi_ordered = _get_wmi_camera_instance_ids_ordered()
    if wmi_ordered:
        if usb_index < len(wmi_ordered):
            actual_path = wmi_ordered[usb_index]
            match = actual_path.upper() == expected_port_path.upper()
            if not match:
                print(
                    f"[CameraIndexer] Cache miss at index {usb_index}: "
                    f"expected {expected_port_path!r}, got {actual_path!r}"
                )
            return match
        else:
            print(f"[CameraIndexer] Index {usb_index} out of WMI device range ({len(wmi_ordered)} devices found)")
            return False

    # Fallback: just verify the camera opens
    try:
        cap = cv2.VideoCapture(usb_index, backend)
        ok = cap.isOpened()
        if ok:
            ret, _ = cap.read()
            ok = ret
        cap.release()
        return ok
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Port map file I/O
# ──────────────────────────────────────────────────────────────────────────────

def _port_map_path(config_dir: str) -> str:
    return os.path.join(config_dir, PORT_MAP_FILENAME)


def load_port_map(config_dir: str) -> Optional[List[Dict[str, Any]]]:
    """
    Load camera_port_map.json.
    Returns list of entry dicts, or None if file doesn't exist or is empty.
    """
    path = _port_map_path(config_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        if not entries:
            return None
        return entries
    except (json.JSONDecodeError, OSError) as e:
        print(f"[CameraIndexer] ERROR reading {path}: {e}")
        return None


def save_port_map(config_dir: str, entries: List[Dict[str, Any]]) -> None:
    """Persist updated entries (including refreshed usb_index_last_seen) to disk."""
    path = _port_map_path(config_dir)
    os.makedirs(config_dir, exist_ok=True)
    data = {
        "schema_version": PORT_MAP_SCHEMA_VERSION,
        "_note": (
            "Auto-generated by camera_indexer.py. "
            "DO NOT edit usb_index_last_seen manually -- it is updated at runtime. "
            "To rebuild, run: python tools/assign_camera_faces.py"
        ),
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def check_port_map_exists(config_dir: str) -> bool:
    """Return True if a valid camera_port_map.json exists."""
    entries = load_port_map(config_dir)
    return entries is not None and len(entries) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Main public API
# ──────────────────────────────────────────────────────────────────────────────

def resolve_camera_indices(
    cameras: List[Dict[str, Any]],
    config_dir: str,
) -> List[Dict[str, Any]]:
    """
    Resolve the correct usb_index for each camera entry based on the saved port map.

    Behaviour
    ---------
    - Non-Windows : returns cameras unchanged (safe no-op).
    - Missing port map : raises RuntimeError -- operator must run wizard first.
    - Clean boot (cached index still correct) : resolves instantly (~0ms).
    - Stale cache (camera moved port) : full re-enumeration, updates cache file.

    Args
    ----
    cameras    : List of camera dicts from load_cameras(). Modified in-place.
    config_dir : Absolute path to the config/ directory.

    Returns
    -------
    Updated cameras list with corrected usb_index values.

    Raises
    ------
    RuntimeError : If port map is missing (first run). Operator must run wizard.
    """
    if sys.platform != "win32":
        print("[CameraIndexer] Non-Windows platform -- skipping port-path resolution.")
        return cameras

    print("\n[CameraIndexer] Resolving camera indices via USB port-path fingerprinting...")

    # ── Load saved port map ──────────────────────────────────────────────────
    entries = load_port_map(config_dir)
    if entries is None:
        raise RuntimeError(
            "\n"
            "================================================================\n"
            "  CAMERA FACE ASSIGNMENT NOT CONFIGURED\n"
            "\n"
            "  camera_port_map.json is missing or empty.\n"
            "  You must run the assignment wizard ONCE before starting\n"
            "  the inspection system:\n"
            "\n"
            "      python tools/assign_camera_faces.py\n"
            "\n"
            "  The wizard will show you each camera's live image and ask\n"
            "  which manifold face it points to (A-F).\n"
            "================================================================\n"
        )

    # Build lookup: face -> entry
    port_map_by_face: Dict[str, Dict[str, Any]] = {
        str(e["face"]).upper(): e
        for e in entries
        if e.get("face") and e.get("port_path")
    }

    # Track stale faces needing re-enumeration
    stale_faces: List[str] = []
    backend = cv2.CAP_DSHOW

    print(f"[CameraIndexer] Verifying {len(cameras)} camera(s) against cached indices...")

    for cam in cameras:
        face = str(cam.get("face", "")).upper()
        if not face:
            continue

        entry = port_map_by_face.get(face)
        if not entry:
            print(
                f"[CameraIndexer] WARNING: Face {face} has no entry in port map -- "
                "keeping cameras.json index as fallback."
            )
            continue

        cached_index = entry.get("usb_index_last_seen")
        port_path = entry.get("port_path", "")

        if cached_index is None:
            stale_faces.append(face)
            continue

        if _verify_index_port_path(cached_index, port_path, backend=backend):
            cam["usb_index"] = cached_index
            print(f"  [OK] Face {face} -> USB index {cached_index}  (port: {port_path})")
        else:
            print(f"  [!!] Face {face}: cached index {cached_index} is stale -- scheduling re-enumeration")
            stale_faces.append(face)

    # ── Slow-path: re-enumerate for stale faces ──────────────────────────────
    if stale_faces:
        print(f"\n[CameraIndexer] Re-enumerating cameras for stale faces: {stale_faces}")
        current_map = _enumerate_cv_index_to_port_path(max_index=9, backend=backend)

        if not current_map:
            print(
                "[CameraIndexer] WARNING: Re-enumeration returned no cameras. "
                "Keeping cached/cameras.json indices as fallback."
            )
        else:
            for cam in cameras:
                face = str(cam.get("face", "")).upper()
                if face not in stale_faces:
                    continue

                entry = port_map_by_face.get(face)
                if not entry:
                    continue

                port_path = entry.get("port_path", "")
                found_index = None

                for idx, path in current_map.items():
                    if path.upper() == port_path.upper():
                        found_index = idx
                        break

                if found_index is not None:
                    cam["usb_index"] = found_index
                    entry["usb_index_last_seen"] = found_index
                    print(f"  [OK] Face {face} -> USB index {found_index}  (re-enumerated, port: {port_path})")
                else:
                    print(
                        f"  [WARN] Face {face}: camera with port_path={port_path!r} NOT found. "
                        f"Check cable. Keeping current index {cam.get('usb_index')} as fallback."
                    )

        # Persist refreshed cache
        save_port_map(config_dir, entries)
        print("[CameraIndexer] Port map cache updated on disk.")

    # ── Print final resolved mapping ─────────────────────────────────────────
    print()
    print("[CameraIndexer] ── Final Resolved Face -> USB Index Mapping ──────────")
    print(f"  {'Face':<6} {'USB':<5} {'Status':<10} {'Port Path'}")
    print(f"  {'----':<6} {'---':<5} {'------':<10} {'--------------------------------------------------'}")
    for cam in cameras:
        face = str(cam.get("face", "?")).upper()
        idx = cam.get("usb_index", "?")
        enabled = cam.get("enabled", True)
        status = "enabled" if enabled else "disabled"
        entry = port_map_by_face.get(face, {})
        port = entry.get("port_path", "(no entry in port map)")
        print(f"  {face:<6} {str(idx):<5} {status:<10} {port}")
    print("[CameraIndexer] ──────────────────────────────────────────────────────")
    print()

    return cameras

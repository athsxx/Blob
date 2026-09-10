"""Locked capture settings used by every Windows camera worker.

Operators cannot change these from the live inspection controls.
Admins unlock with a PIN and save config/capture_profile.json.
Workers read this file when they start (quit and relaunch after a save).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from typing import Any, Dict, List

PROFILE_FILENAME = "capture_profile.json"
DEFAULT_PIN = "2468"

DEFAULT_PROFILE: Dict[str, Any] = {
    "admin_pin": DEFAULT_PIN,
    "width": 320,
    "height": 240,
    "fps": 5,
    "fourcc": "MJPG",
    "backend": "dshow",
}


def profile_path(config_dir: str) -> str:
    return os.path.join(config_dir, PROFILE_FILENAME)


def load_capture_profile(config_dir: str) -> Dict[str, Any]:
    path = profile_path(config_dir)
    data = dict(DEFAULT_PROFILE)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data.update(loaded)
        except (OSError, json.JSONDecodeError):
            pass
    data["width"] = int(data.get("width") or 320)
    data["height"] = int(data.get("height") or 240)
    data["fps"] = float(data.get("fps") or 5)
    data["fourcc"] = str(data.get("fourcc") or "MJPG").upper()
    data["backend"] = str(data.get("backend") or "dshow").lower()
    data["admin_pin"] = str(data.get("admin_pin") or DEFAULT_PIN)
    if data["width"] <= 0:
        data["width"] = 320
    if data["height"] <= 0:
        data["height"] = 240
    if data["fps"] < 1:
        data["fps"] = 5
    if data["fps"] > 10:
        data["fps"] = 10
    return data


def save_capture_profile(config_dir: str, profile: Dict[str, Any]) -> str:
    merged = load_capture_profile(config_dir)
    merged.update(profile)
    path = profile_path(config_dir)
    os.makedirs(config_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)
        f.write("\n")
    return path


def usb_parent_key(port_path: str) -> str:
    """Group cameras by Windows USB parent (e.g. '7' vs '8' = rear vs front)."""
    if not port_path:
        return "unknown"
    tail = str(port_path).replace("/", "\\").split("\\")[-1]
    parts = tail.split("&")
    return parts[0] if parts and parts[0] else "unknown"


def attach_hubs(cameras: List[Dict[str, Any]], port_map_by_face: Dict[str, Dict[str, Any]]) -> None:
    """Stamp port_path, hub_key, and hub id (0, 1, …) onto each camera dict."""
    seen: List[str] = []
    for cam in cameras:
        face = str(cam.get("face", "")).upper()
        entry = port_map_by_face.get(face) or {}
        path = cam.get("port_path") or entry.get("port_path") or ""
        cam["port_path"] = path
        key = usb_parent_key(path)
        cam["hub_key"] = key
        if key not in seen:
            seen.append(key)
    index = {key: i for i, key in enumerate(seen)}
    for cam in cameras:
        cam["hub"] = index.get(cam.get("hub_key"), 0)


def interleave_by_hub(cameras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open one camera per physical USB parent, round-robin, so one hub is not slammed first."""
    enabled = [c for c in cameras if c.get("enabled", True)]
    buckets: Dict[int, deque] = defaultdict(deque)
    for cam in sorted(enabled, key=lambda c: int(c.get("usb_index", 0))):
        buckets[int(cam.get("hub", 0))].append(cam)
    order: List[Dict[str, Any]] = []
    hubs = sorted(buckets)
    while any(buckets[h] for h in hubs):
        for hub in hubs:
            if buckets[hub]:
                order.append(buckets[hub].popleft())
    return order

"""
Configuration Loader Module

Provides unified loading of all JSON configuration files for the
Multi-Camera Manifold Inspection System.

Files loaded:
- config/cameras.json   -> Camera definitions and mappings
- config/rois.json      -> ROI (hole) definitions per camera
- connectivity_rules.json -> Connectivity validation rules
"""

import json
import os
import re
from typing import List, Dict, Optional, Any, Tuple

# Default paths (relative to project root)
CONFIG_DIR = "config"
CAMERAS_FILE = os.path.join(CONFIG_DIR, "cameras.json")
ROIS_FILE = os.path.join(CONFIG_DIR, "rois.json")
RULES_FILE = "connectivity_rules.json"
MANIFOLDS_REGISTRY_FILE = "manifolds_registry.json"

# Shipped defaults when registry file is missing or empty
DEFAULT_MANIFOLD_REGISTRY_ENTRIES: List[Dict[str, str]] = [
    {"label": "DALIA", "folder": "DALIA"},
    {"label": "Manifold 2", "folder": "DALIA"},
    {"label": "Manifold 3", "folder": "DALIA"},
]


def load_manifold_registry_entries(config_dir: str) -> List[Dict[str, Any]]:
    """Load manifold label → config folder mappings from config/manifolds_registry.json."""
    path = os.path.join(config_dir, MANIFOLDS_REGISTRY_FILE)
    if not os.path.isfile(path):
        return [dict(x) for x in DEFAULT_MANIFOLD_REGISTRY_ENTRIES]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ent = data.get("entries") or []
        if not ent:
            return [dict(x) for x in DEFAULT_MANIFOLD_REGISTRY_ENTRIES]
        return list(ent)
    except (json.JSONDecodeError, OSError):
        return [dict(x) for x in DEFAULT_MANIFOLD_REGISTRY_ENTRIES]


def save_manifold_registry_entries(config_dir: str, entries: List[Dict[str, Any]]) -> None:
    path = os.path.join(config_dir, MANIFOLDS_REGISTRY_FILE)
    os.makedirs(config_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, indent=2)


def manifold_labels(config_dir: str) -> List[str]:
    labels = [str(e["label"]) for e in load_manifold_registry_entries(config_dir) if e.get("label")]
    return labels if labels else ["DALIA"]


def manifold_folder_for_label(manifold_label: str, config_dir: str) -> Optional[str]:
    label = str(manifold_label).strip()
    for e in load_manifold_registry_entries(config_dir):
        if str(e.get("label", "")).strip() == label:
            return str(e.get("folder") or "DALIA")
    return None


def list_config_subdirs_with_rules(config_dir: str) -> List[str]:
    """Folder names under config_dir that contain connectivity_rules.json (for copy template)."""
    out: List[str] = []
    if not os.path.isdir(config_dir):
        return out
    for name in sorted(os.listdir(config_dir)):
        p = os.path.join(config_dir, name)
        if os.path.isdir(p) and os.path.isfile(os.path.join(p, "connectivity_rules.json")):
            out.append(name)
    return out


def slug_manifold_folder_id(display_name: str) -> str:
    """Filesystem-safe folder name from a display name."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (display_name or "").strip()).strip("_")
    return s or "Manifold"


def validate_manifold_folder_id(folder_id: str) -> Tuple[bool, str]:
    if not folder_id or not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", folder_id):
        return False, "Use letters, numbers, underscore, or hyphen (must start with a letter or number)."
    if folder_id in (".", ".."):
        return False, "Invalid folder name."
    return True, ""


def load_all_cameras_from_file(cameras_file: str) -> List[Dict[str, Any]]:
    """All camera entries in cameras.json (including disabled), for face→USB and ROI filenames."""
    data = _load_json(cameras_file)
    if not data:
        return []
    return list(data.get("cameras", []))


def manifold_data_subdirectory(manifold: str, config_dir: Optional[str] = None) -> str:
    """
    Folder name under config/ where ROI files (hole_positions_*.json) live.
    If config_dir is set, resolves via manifolds_registry.json.
    Legacy fallback when config_dir is omitted (e.g. older call sites).
    """
    if config_dir:
        folder = manifold_folder_for_label(manifold, config_dir)
        if folder:
            return folder
    if not manifold:
        return "DALIA"
    m = str(manifold).strip()
    if m in ("Manifold 2", "Manifold 3"):
        return "DALIA"
    return m or "DALIA"


def _load_json(filepath: str) -> Optional[Dict[str, Any]]:
    """
    Load and parse a JSON file.
    
    Args:
        filepath: Path to the JSON file
        
    Returns:
        Parsed JSON dict or None if file not found/invalid
    """
    if not os.path.exists(filepath):
        print(f"[ConfigLoader] Warning: File not found: {filepath}")
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ConfigLoader] Error parsing {filepath}: {e}")
        return None


def validate_enabled_cameras(cameras: List[Dict[str, Any]]) -> List[str]:
    """
    Return human-readable errors for enabled camera entries (missing fields).
    Does not reject unknown optional keys.
    """
    errors: List[str] = []
    for i, cam in enumerate(cameras):
        if not cam.get("enabled", True):
            continue
        prefix = f"Camera entry #{i + 1}"
        if cam.get("usb_index") is None:
            errors.append(f"{prefix}: missing usb_index")
        if not cam.get("face"):
            errors.append(f"{prefix}: missing face")
        if not cam.get("config"):
            errors.append(f"{prefix}: missing config (ROI filename)")
    return errors


def connectivity_rules_path_ok(project_root: str, config_subfolder: str) -> tuple:
    """
    Return (True, path) if rules file exists and contains a non-empty 'rules' list.
    Otherwise (False, path_or_expected).
    """
    path = os.path.normpath(
        os.path.join(project_root, CONFIG_DIR, config_subfolder, RULES_FILE)
    )
    if not os.path.isfile(path):
        return False, path
    data = _load_json(path)
    if not data:
        return False, path
    rules = data.get("rules")
    if not isinstance(rules, list) or len(rules) == 0:
        return False, path
    return True, path


def load_cameras(filepath: str = CAMERAS_FILE) -> List[Dict[str, Any]]:
    """
    Load camera configurations.
    
    Returns:
        List of camera config dicts with keys:
        - usb_index: int
        - face: str (e.g., "A")
        - config: str (path to hole positions file)
        - hub: int (optional, hub number)
        - enabled: bool
    """
    data = _load_json(filepath)
    if data is None:
        return []
    
    cameras = data.get("cameras", [])
    
    # Filter to only enabled cameras
    enabled_cameras = [c for c in cameras if c.get("enabled", True)]
    
    print(f"[ConfigLoader] Loaded {len(enabled_cameras)}/{len(cameras)} enabled cameras.")
    return enabled_cameras


def get_camera_by_face(cameras: List[Dict], face: str) -> Optional[Dict]:
    """Find camera config for a specific face."""
    for cam in cameras:
        if cam.get("face") == face:
            return cam
    return None


def get_face_by_usb_index(cameras: List[Dict], usb_index: int) -> Optional[str]:
    """Get the face letter for a USB index."""
    for cam in cameras:
        if cam.get("usb_index") == usb_index:
            return cam.get("face")
    return None


def load_rois(filepath: str = ROIS_FILE, camera_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Load ROI (Region of Interest) definitions.
    
    Args:
        filepath: Path to rois.json
        camera_id: If provided, filter ROIs for this camera only
        
    Returns:
        List of ROI dicts with keys:
        - roi_id: str (e.g., "A_A1")
        - camera_id: str
        - face: str
        - hole_id: str
        - shape: str ("circle" or "rectangle")
        - cx, cy, radius (for circles)
        - x, y, width, height (for rectangles)
    """
    data = _load_json(filepath)
    if data is None:
        return []
    
    rois = data.get("rois", [])
    
    # Filter by camera_id if specified
    if camera_id:
        rois = [r for r in rois if r.get("camera_id") == camera_id]
        print(f"[ConfigLoader] Loaded {len(rois)} ROIs for {camera_id}.")
    else:
        print(f"[ConfigLoader] Loaded {len(rois)} total ROIs.")
    
    return rois


def load_rules(filepath: str = RULES_FILE) -> List[Dict[str, Any]]:
    """
    Load connectivity validation rules.
    
    Returns:
        List of rule dicts with keys:
        - rule_id: str (e.g., "FACE_A_A1")
        - input: {face: str, hole_id: str}
        - expected_outputs: [{face, hole_id, mandatory}, ...]
        - logic: str ("AND" or "OR")
        - timing: {max_delay_ms: int, min_stable_frames: int}
    """
    data = _load_json(filepath)
    if data is None:
        return []
    
    rules = data.get("rules", [])
    print(f"[ConfigLoader] Loaded {len(rules)} connectivity rules.")
    return rules


def get_rules_by_face(rules: List[Dict], face: str) -> List[Dict]:
    """
    Filter rules by input face.
    
    Args:
        rules: List of all rules
        face: Face to filter by (e.g., "A")
        
    Returns:
        Rules where input.face matches
    """
    return [r for r in rules if r.get("input", {}).get("face") == face]


def get_rules_by_input_hole(rules: List[Dict], face: str, hole_id: str) -> List[Dict]:
    """
    Find rules that match a specific input hole.
    
    Args:
        rules: List of all rules
        face: Input face
        hole_id: Input hole ID
        
    Returns:
        Matching rules
    """
    return [
        r for r in rules 
        if r.get("input", {}).get("face") == face 
        and r.get("input", {}).get("hole_id") == hole_id
    ]


# --- Validation Helpers ---

def validate_cameras(cameras: List[Dict]) -> bool:
    """Check that all cameras have required fields."""
    required = {"camera_id", "usb_index", "face", "resolution", "fps"}
    for cam in cameras:
        if not required.issubset(cam.keys()):
            print(f"[ConfigLoader] Invalid camera config: {cam}")
            return False
    return True


def validate_rois(rois: List[Dict]) -> bool:
    """Check that all ROIs have required fields."""
    required = {"roi_id", "camera_id", "face", "hole_id", "shape"}
    for roi in rois:
        if not required.issubset(roi.keys()):
            print(f"[ConfigLoader] Invalid ROI config: {roi}")
            return False
        
        # Check shape-specific fields
        if roi["shape"] == "circle":
            if not all(k in roi for k in ["cx", "cy", "radius"]):
                print(f"[ConfigLoader] Circle ROI missing coords: {roi['roi_id']}")
                return False
    return True


# --- Main (for testing) ---

if __name__ == "__main__":
    print("=" * 50)
    print("CONFIG LOADER TEST")
    print("=" * 50)
    
    cameras = load_cameras()
    print(f"\nCameras: {[c['camera_id'] for c in cameras]}")
    
    rois = load_rois()
    print(f"Total ROIs: {len(rois)}")
    
    # Test filtering
    rois_a = load_rois(camera_id="CAM_A")
    print(f"ROIs for CAM_A: {len(rois_a)}")
    
    rules = load_rules()
    print(f"Total Rules: {len(rules)}")
    
    # Test rule lookup
    face_a_rules = get_rules_by_face(rules, "A")
    print(f"Rules for Face A: {len(face_a_rules)}")
    
    print("\n" + "=" * 50)
    print("Validation:")
    print(f"  Cameras valid: {validate_cameras(cameras)}")
    print(f"  ROIs valid: {validate_rois(rois)}")

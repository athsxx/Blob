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
from typing import List, Dict, Optional, Any

# Default paths (relative to project root)
CONFIG_DIR = "config"
CAMERAS_FILE = os.path.join(CONFIG_DIR, "cameras.json")
ROIS_FILE = os.path.join(CONFIG_DIR, "rois.json")
RULES_FILE = "connectivity_rules.json"


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

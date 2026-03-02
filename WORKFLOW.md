# Operator Workflow Guide

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Check cameras are connected
python diagnose_cameras.py

# 3. Calibrate ROIs (one camera at a time)
python calibrate.py --cam 0
python calibrate.py --cam 1

# 4. Test detection (single camera)
python detect.py --cam 0

# 5. Run full system
python src/main.py
```

---

## Step-by-Step

### 1. Diagnose Cameras

Run **once** after plugging in cameras to verify they're detected:

```bash
python diagnose_cameras.py
```

You should see all connected cameras with their USB indices. Note which index maps to which face of the manifold.

### 2. Update Camera Config

Edit `config/cameras.json` to map USB indices to manifold faces:

| Field | Description |
|-------|-------------|
| `usb_index` | The USB camera index from Step 1 |
| `face` | Which manifold face this camera views (A–F) |
| `enabled` | Set `false` to disable a camera |
| `config` | Path to hole positions file |

### 3. Calibrate ROIs

Draw ellipse regions of interest around each hole:

```bash
python calibrate.py --cam 0
```

**Controls:**
| Key | Action |
|-----|--------|
| Click | Select nearest ellipse |
| Arrow keys | Move selected ellipse |
| `+` / `-` | Resize |
| `r` / `R` | Rotate |
| `a` | Add new ellipse |
| `d` | Delete selected |
| `n` | Rename selected |
| `s` | Save config |
| `q` | Quit |

Repeat for each camera. Config saves to `config/rois_webcam.json`.

### 4. Test Detection

Verify detection works before running the full system:

```bash
python detect.py --cam 0 --config config/rois_webcam.json
```

Point a green laser at the manifold holes and verify:
- Green circles = stable detection ✓
- Yellow circles = detecting but not yet stable
- Gray circles = no detection

**Controls:**
| Key | Action |
|-----|--------|
| `q` | Quit |
| `s` | Save snapshot |
| `r` | Reset statistics |

### 5. Quick Test Suite

Runs calibration then detection in sequence:

```bash
python run_test_suite.py
```

### 6. Run Full System

Launch all cameras with the inspection dashboard:

```bash
python src/main.py          # PyQt6 dashboard (recommended)
python src/main.py --cv     # OpenCV fallback dashboard
python src/main.py --no-display  # Headless mode (logging only)
```

The dashboard shows:
- **2×3 camera grid** — live feeds from all faces
- **Inspection panel** — current rule, expected outputs, PASS/FAIL
- **Progress bar** — rules tested vs. total
- **Results log** — timestamped history

---

## File Reference

| File | Purpose |
|------|---------|
| `calibrate.py` | Interactive ROI calibration |
| `detect.py` | Single-camera laser detection test |
| `diagnose_cameras.py` | Camera connectivity check |
| `run_test_suite.py` | Guided calibrate → detect flow |
| `laser_detector_lib.py` | Core detection library (HSV color) |
| `src/main.py` | Production entry point |
| `src/camera_worker.py` | Per-camera capture process |
| `src/dashboard.py` | PyQt6 / OpenCV dashboard |
| `src/logic_engine.py` | Connectivity rule evaluator |
| `src/config_loader.py` | JSON config loading |
| `src/logger.py` | CSV/JSONL logging |
| `config/cameras.json` | Camera ↔ face mapping |
| `config/rois_webcam.json` | Calibrated ROI positions |
| `connectivity_rules.json` | Connectivity rules |

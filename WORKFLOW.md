# Operator Workflow Guide

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Check cameras (engineer)
python diagnose_cameras.py

# 3. Run the app
python src/main.py
```

Daily path (port map already saved): **Mode → live tiles → wait for Opening cameras → START**.

Place or fix hole ROIs from **Admin → Edit hole ROIs** after cameras are open. Do not run `calibrate.py` while `main.py` is live.

---

## Step-by-Step

### 1. Diagnose Cameras (first install)

```bash
python diagnose_cameras.py
```

### 2. Assign camera faces

In the app, **Admin → Assign camera faces** (or the first-launch wizard). That writes `config/camera_port_map.json`. Quit and relaunch after a new assignment.

### 3. Edit hole ROIs

After the Opening-cameras overlay finishes: **Admin → PIN → Edit hole ROIs**. Pick a face, wait for the snapshot, drag ellipses, **Save**. Face A writes `config/DALIA/hole_positions_cam0.json` … Face F `cam5.json`.

Lab fallback only after a full quit:

```bash
python calibrate.py --cam 0 --config config/DALIA/hole_positions_cam0.json
```

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

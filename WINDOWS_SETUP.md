# Windows Setup & Operation Guide

## Prerequisites (One-Time Setup)

### Step 1: Install Python 3.10+

1. Download Python from [python.org/downloads](https://www.python.org/downloads/)
2. **IMPORTANT**: During installation, check **"Add Python to PATH"**
3. Verify installation — open **Command Prompt** (Win+R → `cmd`):
   ```
   python --version
   ```
   Should show `Python 3.10.x` or higher.

### Step 2: Extract the Zip

1. Copy `Blob.zip` to your desired location (e.g. `C:\Inspection\`)
2. Right-click → **Extract All**
3. You should now have `C:\Inspection\Blob\`

### Step 3: Install Dependencies

Open **Command Prompt**, navigate to the project:
```
cd C:\Inspection\Blob
pip install -r requirements.txt
```

This installs: `opencv-python`, `numpy`, `PyQt6`

---

## Camera Setup

### Step 4: Connect Cameras

1. Connect all USB cameras to the **powered USB hub**(s)
2. Connect hub(s) to the PC
3. Wait 5 seconds for Windows to detect them

### Step 5: Diagnose Cameras

Run from the Blob directory:
```
python diagnose_cameras.py
```

**Expected output:**
```
Camera 0: CONNECTED (1280x800 @ 30fps)
Camera 1: CONNECTED (1280x800 @ 30fps)
...
```

**Note the USB index** for each camera — you'll need this for Step 6.

### Step 6: Update Camera Config

Edit `config\cameras.json` in Notepad:
```
notepad config\cameras.json
```

For each camera, set:
- `"usb_index"` — the number from Step 5
- `"face"` — which face of the manifold (A through F)
- `"enabled"` — `true` or `false`

---

## Calibration

### Step 7: Calibrate ROIs (Each Camera)

Run for each camera (replace `0` with actual USB index):
```
python calibrate.py --cam 0
python calibrate.py --cam 1
python calibrate.py --cam 2
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
| `s` | **Save config** |
| `q` | Quit |

> **IMPORTANT**: Press `s` to save before quitting!

Config saves to `config\rois_webcam.json`

---

## Testing

### Step 8: Test Detection (Single Camera)

Test each camera individually before running full system:
```
python detect.py --cam 0 --config config\rois_webcam.json
```

- Point the green laser at each hole
- **Green circle** = laser detected ✓
- **Gray circle** = no detection

Press `q` to quit.



## Running the Full System

### Step 10: Launch System

```
python src\main.py
```

**Alternative modes:**
```
python src\main.py --cv           # OpenCV fallback (if PyQt6 has issues)
python src\main.py --no-display   # Headless mode (logging only)
```

### Step 10: Operate the Dashboard

When the application launches, follow the 3-stage flow:

1. **Mode Selection**: Click **Sequential Inspection**
2. **Manifold Selection**: Choose your target manifold (e.g. **DALIA**) from the dropdown menu, then click **▶ START INSPECTION**.
3. **Live Dashboard**: The camera feeds appear dynamically, and the Logic Engine loads the rules specific to your selected manifold.
4. Watch the **Inspection Panel** on the left for rule progression.
5. Use the control buttons across the top:

| Button | What it Does |
|--------|-------------|
| ▶ START | Begin inspection (resets counters) |
| ■ STOP | End inspection (resets everything) |
| ⏸ PAUSE | Pause rule evaluation (cameras stay live) |
| ⏵ RESUME | Resume after pause |
| ✎ OVERRIDE | Manually mark a rule as PASS or FAIL |

5. Press **Ctrl+C** in the terminal or close the window to shut down

---

## Manual Override

If a rule fails but you visually confirm the laser:

1. Click **✎ OVERRIDE**
2. Select the rule from the dropdown
3. Choose **PASS** or **FAIL**
4. Click **OK**

The override is logged to the inspection log.

---

## File Reference

```
Blob\
├── config\
│   ├── DALIA\                ← Manifold-specific configuration
│   │   ├── connectivity_rules.json   ← Inspection rules (DALIA)
│   │   └── hole_positions_cam*.json  ← Calibrated ROI positions
│   ├── cameras.json          ← Camera USB mapping
│   └── rois_webcam.json      ← General ROI mapping test file
├── src\
│   ├── main.py               ← System entry point
│   ├── camera_worker.py      ← Per-camera capture process
│   ├── dashboard.py          ← PyQt6 dashboard UI
│   ├── logic_engine.py       ← Rule evaluation engine
│   ├── config_loader.py      ← Configuration loading
│   └── logger.py             ← Inspection logging
├── calibrate.py              ← ROI calibration tool
├── detect.py                 ← Single-camera detection test
├── diagnose_cameras.py       ← Camera connectivity check
├── show_camera_indices.py    ← USB enumeration diagnostic
├── laser_detector_lib.py     ← Core detection library
├── requirements.txt          ← Python dependencies
├── WORKFLOW.md               ← Quick-reference workflow
├── WINDOWS_SETUP.md          ← This file
└── logs\                     ← Auto-generated inspection logs
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python` not found | Re-install Python with "Add to PATH" checked |
| Camera not detected | Try different USB port, check Device Manager |
| Black camera feed | Ensure no other app is using the camera |
| PyQt6 error | Run with `--cv` flag for OpenCV fallback |
| Slow display | Normal on first launch; stabilizes after warm-up |
| Permission error | Run Command Prompt as Administrator |

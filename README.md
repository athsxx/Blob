# Manifold Inspection System

Multi-camera laser detection system for industrial manifold connectivity testing. Uses 5 USB cameras to verify hole-to-hole connectivity by detecting green laser light passing through manifold passages.

## Features

- **5-Camera Simultaneous Capture** — each camera monitors one face of the manifold
- **Green Laser Detection** — HSV + RGB dominance analysis for accurate laser spot detection
- **65 Connectivity Rules** — automated PASS/FAIL evaluation per hole connection
- **Guided Sequential Inspection** — step-by-step operator instructions
- **PyQt6 Dashboard** — live camera feeds, rule status, progress tracking
- **Auto-Reconnect** — cameras recover from disconnects automatically
- **Logging** — CSV + JSON-lines for traceability and Excel analysis

## Project Structure

```
Blob/
├── src/                        # Core application
│   ├── main.py                 # Entry point
│   ├── camera_worker.py        # Camera capture + laser detection
│   ├── dashboard.py            # PyQt6 operator dashboard
│   ├── logic_engine.py         # Rule evaluation engine
│   ├── config_loader.py        # JSON config loading
│   ├── logger.py               # Inspection logging (CSV + JSONL)
│   └── start_screen.py         # Mode selection screen
├── config/
│   ├── cameras.json            # Camera index → face mapping
│   ├── rois.json               # ROI definitions
│   └── DALIA/                  # Manifold-specific config
│       ├── connectivity_rules.json
│       └── hole_positions_cam*.json
├── calibrate.py                # ROI calibration tool
├── diagnose_cameras.py         # Camera diagnostic utility
├── show_camera_indices.py      # Capture labeled frames per camera
├── display_cameras_15fps.py    # Multi-camera viewer (standalone)
└── list_mac_cameras.py         # List AVFoundation devices (macOS)
```

## Requirements

- Python 3.9+
- 5 USB webcams
- macOS or Windows

## Installation

```bash
# Clone the repo
git clone https://github.com/athsxx/Blob.git
cd Blob

# Create virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

### 1. Diagnose Cameras

First, check which cameras are detected and at which USB indices:

```bash
python diagnose_cameras.py
```

This scans indices 0–9 and shows resolution, FPS, and read status for each.

### 2. Identify Cameras

Capture a labeled snapshot from each camera to identify which physical camera maps to which index:

```bash
python show_camera_indices.py
```

Check the `camera_indices_check/` folder for labeled images.

### 3. Configure Cameras

Edit `config/cameras.json` to map each USB index to the correct manifold face (A–E):

```json
{
  "usb_index": 0,
  "face": "A",
  "config": "hole_positions_cam0.json",
  "enabled": true
}
```

### 4. Calibrate ROIs

For each camera, calibrate the hole positions (drag ellipses over each hole):

```bash
python calibrate.py --cam 0
python calibrate.py --cam 1
# ... repeat for each camera
```

**Controls:**
- Drag to move ellipse
- `+`/`-` — adjust width
- `[`/`]` — adjust height
- `R` — rotate
- `N` — add new ROI
- `D` — delete selected
- `S` — save

### 5. Run Inspection

```bash
cd src
python main.py
```

This launches:
1. **Start Screen** — select "Sequential Inspection"
2. **Dashboard** — shows live camera feeds, current step instruction, and PASS/FAIL results
3. **Guided Flow** — follow on-screen instructions to insert laser into each hole

### 6. View Results

Inspection results are logged to:
- `logs/inspection_YYYY-MM-DD.csv` — summary for Excel
- `logs/inspection_YYYY-MM-DD.jsonl` — full detail

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `diagnose_cameras.py` | List all detected cameras and their capabilities |
| `show_camera_indices.py` | Save labeled snapshots to identify cameras |
| `display_cameras_15fps.py` | Standalone multi-camera viewer at 15 FPS |
| `list_mac_cameras.py` | List AVFoundation devices (macOS only) |
| `calibrate.py` | Interactive ROI calibration per camera |

## Windows Setup

See [WINDOWS_SETUP.md](WINDOWS_SETUP.md) for Windows-specific instructions including driver configuration and camera index adjustment.

## Configuration Reference

### `config/cameras.json`

Defines which cameras are active and how they map to manifold faces.

| Field | Type | Description |
|-------|------|-------------|
| `usb_index` | int | OS-level camera index (0–5) |
| `face` | string | Manifold face this camera views (A–F) |
| `config` | string | Hole positions JSON filename |
| `enabled` | bool | Whether this camera is active |
| `fps` | int | Target frames per second |
| `backend` | string | `"auto"`, `"avfoundation"`, or `"dshow"` |

### `config/DALIA/connectivity_rules.json`

Contains all 65 inspection rules. Each rule defines:
- **Input**: which face/hole the laser is inserted into
- **Expected Outputs**: which face/hole(s) the laser should emerge from
- **Logic**: `AND` (all outputs required) or `OR` (any output sufficient)

## License

Internal use — GnB Plant 8

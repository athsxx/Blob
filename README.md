# Manifold Inspection System (Blob)

Multi-camera laser detection for industrial manifold connectivity testing. Up to **six USB cameras** (faces **A–F**) watch the manifold; the app detects green laser light in calibrated hole ROIs and evaluates **connectivity rules** (PASS/FAIL).

---

## Requirements

- **Python 3.9+**
- **OpenCV**, **NumPy**, **PyQt6** (see `requirements.txt`)
- **Six USB webcams** (or fewer — disable unused faces in `config/cameras.json`)
- **macOS** or **Windows** (Linux is untested but may work with V4L2)

---

## Installation

```bash
git clone https://github.com/athsxx/Blob.git
cd Blob
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Run commands

All commands below assume the repo root is your current directory (`Blob/`).

| Command | Purpose |
|--------|---------|
| `python src/main.py` | **Normal run** — PyQt6 dashboard, full UI flow |
| `python src/main.py --cv` | Force **OpenCV** dashboard instead of PyQt6 |
| `python src/main.py --no-display` | **Headless** — no preview windows (workers + logic still run) |
| `python src/main.py --config-dir /path/to/config` | Use an alternate config directory (must contain `cameras.json`) |

**Working directory:** Prefer running from the **repo root** so relative paths in logs and tools stay consistent. The entry point lives at `src/main.py`.

### Helper / diagnostic scripts (repo root)

| Command | Purpose |
|--------|---------|
| `python diagnose_cameras.py` | Scan camera indices and capabilities |
| `python show_camera_indices.py` | Save labeled snapshots (e.g. under `camera_indices_check/`) to match **USB index → physical camera** |
| `python calibrate.py --cam N --config PATH` | ROI calibration for USB index `N`, writing to `PATH` (see [ROI calibration](#roi-calibration)) |
| `python display_cameras_15fps.py` | Standalone multi-camera viewer |
| `python list_mac_cameras.py` | macOS: list AVFoundation devices |

---

## Operator flow (exact UI sequence)

1. **Launch**  
   Run `python src/main.py`.

2. **Mode (screen 1)**  
   Choose **Sequential inspection** (full guided sequence) or **Manual inspection** (pick one rule after setup).

3. **Manifold (screen 2)**  
   Choose **DALIA**, **Manifold 2**, or **Manifold 3**.  
   Use **← Back** to return to mode.  
   **Manifold 2 / 3** currently use the same **rules** and **ROI file folder on disk** as **DALIA** (`config/DALIA/`) until separate manifold folders are added.

4. **Manual only (screen 3)**  
   If you chose manual: pick **manifold**, **input face**, **rule**, then **Continue**. **← Back** returns to manifold selection.

5. **Before live inspection (screen 4 — pre-inspection)**  
   - **Calibrate ROIs…** — optional; opens the calibration dialog (see below). **Recommended** if you need to adjust holes; cameras are usually **not** opened by the main app yet, so the USB device is free.  
   - **Continue to live inspection** — proceeds to the live dashboard and allows `main.py` to finish setup (logic engine, workers, etc.).  
   - **← Back** — returns to manifold (sequential) or manual setup (manual).

6. **Live dashboard (screen 5)**  
   **START / STOP / PAUSE / RESUME**, step list, instructions, camera tiles.  
   **USB map** and **Calibrate ROIs** remain available here. If workers already hold the cameras, close or stop using the camera before calibrating the same index in OpenCV.

7. **Sequential**  
   Follow guided steps: insert laser where indicated; the system checks expected outputs and records PASS/FAIL.

8. **Logs**  
   Under `logs/` (e.g. CSV and JSONL per day) — use for traceability and analysis.

---

## ROI calibration

### When it runs

- **Only when you start it** — either **Calibrate ROIs…** on the **pre-inspection** page, **Calibrate ROIs** on the **live dashboard**, or by running `calibrate.py` yourself.

### Where it saves

- The UI launches `calibrate.py` with an explicit `--config` path, typically:  
  `config/<manifold-folder>/hole_positions_camN.json`  
  where **N** matches the **USB index** for that face in `cameras.json` (convention: Face **A → cam0**, … **F → cam5**).  
- **Manifold 2 / 3** still read/write ROI files under **`config/DALIA/`** (same as rules) via `manifold_data_subdirectory()` in `src/config_loader.py`.

### Persisting changes

- In the OpenCV calibration window, press **`s`** to **save** to the JSON file.  
- **`q`** quits **without** auto-save.  
- Unsaved edits are lost.

### `calibrate.py` controls (reference)

- **Drag** — move selected ellipse  
- **`+` / `-`** — width  
- **`[` / `]`** — height  
- **Left / Right arrow** — rotate ±5°  
- **`a`** add · **`d`** delete · **`c`** copy · **`n`** rename  
- **`s`** **SAVE** · **`q`** quit · **Space** refresh frame  

### Manual CLI example

From repo root, after you know the absolute path to the ROI file:

```bash
python calibrate.py --cam 0 --config /absolute/path/to/Blob/config/DALIA/hole_positions_cam0.json
```

If you omit `--config`, `calibrate.py` tries to resolve the file from `config/cameras.json` (may not match manifold-specific paths — prefer explicit `--config` when using DALIA subfolder layouts).

---

## Configuration

### `config/cameras.json`

- Maps **`usb_index`** → **`face`** (A–F) and **`config`** (filename like `hole_positions_cam0.json`).  
- **`enabled: false`** skips that camera (worker not started).  
- **USB map** in the dashboard writes this file; **restart the application** after saving so workers reload.

### Standard layout (recommended)

| Face | USB index | ROI file (under `config/DALIA/` or manifold folder) |
|------|-----------|--------------------------------------------------------|
| A | 0 | `hole_positions_cam0.json` |
| B | 1 | `hole_positions_cam1.json` |
| C | 2 | `hole_positions_cam2.json` |
| D | 3 | `hole_positions_cam3.json` |
| E | 4 | `hole_positions_cam4.json` |
| F | 5 | `hole_positions_cam5.json` |

### `config/DALIA/connectivity_rules.json`

Defines input holes vs expected outputs and PASS/FAIL logic for guided and reactive modes.

---

## Troubleshooting

### `No cameras configured` / empty camera list

- Check **`config/cameras.json`** exists under your **`--config-dir`**.  
- Ensure at least one camera has **`enabled: true`**.

### PyQt6 / Qt platform plugin error (macOS)

- `src/main.py` sets **`QT_QPA_PLATFORM_PLUGIN_PATH`** to PyQt6’s `Qt6/plugins/platforms` when possible.  
- If it still fails: install PyQt6 in the same environment you use to run `python src/main.py`, or run with **`python src/main.py --cv`** to use the OpenCV fallback.

### Calibration fails or shows wrong camera

- Confirm **`--cam`** matches the **USB index** in `cameras.json` for that face.  
- Use **`show_camera_indices.py`** or the dashboard **USB map** scan to match physical ports to indices.

### `Could not open camera` / device busy

- Another app (including a **previous** calibration window or a stuck worker) may hold the device. Quit other camera apps, stop inspection, or restart the process.

### Detection always wrong / no laser found

- Recalibrate ROIs (**`s`** to save).  
- Resolution or zoom changed → ROI pixel coordinates no longer align; recalibrate.  
- Check lighting and that the laser is visible and green-dominant in the ROI (see `camera_worker.py` detection tuning if needed).

### Manifold 2 or 3 “missing” ROI files

- ROI and rules paths for **Manifold 2 / 3** intentionally use **`config/DALIA/`** until you add dedicated folders and update `manifold_data_subdirectory()` in `config_loader.py`.

### After editing `cameras.json` on disk

- **Restart** the full application so camera workers reload **usb_index** / **enabled** / **config** paths.

### Wrong rule set

- Rules file is chosen in `main.py` after manifold selection (currently all map to `config/DALIA/connectivity_rules.json` for POC).

---

## Project structure (short)

```
Blob/
├── src/
│   ├── main.py              # Entry point
│   ├── camera_worker.py     # Capture + laser detection
│   ├── dashboard.py         # PyQt6 UI (stacked setup + live dashboard)
│   ├── logic_engine.py      # Rules + guided sequence
│   ├── config_loader.py     # JSON load + manifold ROI folder helper
│   ├── camera_setup_ui.py   # USB map + Calibrate ROI dialog
│   └── logger.py
├── config/
│   ├── cameras.json
│   └── DALIA/
│       ├── connectivity_rules.json
│       └── hole_positions_cam*.json
├── calibrate.py
├── diagnose_cameras.py
├── show_camera_indices.py
├── requirements.txt
└── README.md
```

---

## License / use

Internal use — GnB Plant 8.

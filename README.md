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

### Helper / diagnostic scripts (engineer only)

These are **not** the daily operator path. Prefer **Admin → Assign camera faces** and **Admin → Edit hole ROIs** inside `python src/main.py`.

| Command | Purpose |
|--------|---------|
| `python diagnose_cameras.py` | Scan camera indices and capabilities |
| `python calibrate.py --cam N --config PATH` | Lab ROI tool — **quit `main.py` first**; Face A = `hole_positions_cam0.json` (not USB index) |

---

## Operator flow (exact UI sequence)

1. **Launch**  
   Run `python src/main.py`. If `camera_port_map.json` is missing (first Windows install), complete **Assign camera faces**.

2. **Mode**  
   Choose **Sequential** (full guided sequence) or **Manual (single rule)** (testing).

3. **Manifold**  
   Sequential with more than one model: pick **DALIA** (or last used). A single model skips this page. Manual: pick manifold, face, and rule on the next page.

4. **Live dashboard**  
   Wait for **Opening cameras — Face X (n of 6)**. Do not close the window. **START** stays off until workers report ready.

5. **START**  
   Starts **logic only** (cameras are already open). Follow guided steps. **OVERRIDE** stays on the bar for testing.

6. **Admin (PIN)**  
   **Edit hole ROIs** (freeze live frame, drag ellipses, Save — cameras stay up). **Assign camera faces** (quit and relaunch after saving). Capture lock still needs a full relaunch.

7. **Logs**  
   Under `logs/` (CSV / JSONL per day, plus `camera_face_X.log`).

---

## ROI calibration

Shop-floor path: **Admin → PIN → Edit hole ROIs** after cameras are open. Snapshot comes from the live worker (no second `VideoCapture`). Hole names come from `connectivity_rules.json`. Face A writes `hole_positions_cam0.json` … Face F `cam5.json`. Save writes `calib_width` / `calib_height` and reloads masks without restarting.

Lab fallback (app fully quit): `python calibrate.py --cam N --config config/DALIA/hole_positions_cam0.json` for Face A. `N` is the USB index; the filename `cam0` is the **face ordinal**.

### Manual CLI example

From repo root, **after quitting** `main.py`:

```bash
python calibrate.py --cam 0 --config config/DALIA/hole_positions_cam0.json
```

---

## Configuration

### `config/cameras.json`

- Maps **`usb_index`** → **`face`** (A–F) and **`config`** (filename like `hole_positions_cam0.json`).  
- **`enabled: false`** skips that camera (worker not started).  
- **Admin → Assign camera faces** writes the port map; **quit and relaunch** after saving so workers reopen the correct USB indices.

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

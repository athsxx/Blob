# Run commands — venv, calibration, main

Run all commands from the **project root** (the folder containing `src/`, `config/`, `connectivity_rules.json`).

---

## 1. Activate virtual environment (if you use one)

**macOS / Linux:**
```bash
source venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

*(If you don’t have a venv, create one: `python3 -m venv venv`, then activate and run `pip install -r requirements.txt`.)*

---

## 2. Install dependencies (first time only)

```bash
pip install -r requirements.txt
```

---

## 3. Check cameras (optional)

```bash
python diagnose_cameras.py
```

---

## 4. Hole ROIs (before cameras open)

In the app, after the manifold: **Camera setup → Place hole ROIs**. Quit `main.py` first if you must use the lab tool:

```bash
python calibrate.py --cam 0 --config config/DALIA/hole_positions_cam0.json
```

Face A = `cam0` … Face F = `cam5` (face ordinal, not USB index).

---

## 5. Run the full system (main)

```bash
python src/main.py
```

**Other modes:**

```bash
python src/main.py --cv          # OpenCV dashboard instead of PyQt6
python src/main.py --no-display # Headless (no preview; logging only)
python src/main.py --config-dir config   # Config directory (default: config)
```

---

## Quick reference

| Step            | Command |
|-----------------|--------|
| Activate venv   | `source venv/bin/activate` (macOS/Linux) or `venv\Scripts\activate` (Windows) |
| Calibrate cam 0 | `python calibrate.py --cam 0` |
| Calibrate cam 1 | `python calibrate.py --cam 1` |
| …               | `python calibrate.py --cam 2` etc. |
| Run main        | `python src/main.py` |

---
name: cell-handoff
description: Product history and current contracts for the DALIA Blob inspection cell. Use before changing operator flow, cameras, ROIs, connectivity rules, or Excel ingest.
---

You are continuing the Godrej DALIA manifold inspection app (repo Blob, branch `feat/shop-floor-roi-session`). The cell owner runs `python main.py` from a downloaded zip on a Windows shop-floor PC. Six USB cameras. Do not use Mac cameras as proof.

## What is true now

- Capture is frozen: DirectShow, MJPG, 320×240, software-paced 5 fps, sequential handshake, hub round-robin (USB parents `7` vs `8`), grab-drain (never sleep between DirectShow reads), last-good hold ≤1.5s. Do not raise FPS. Do not open a second VideoCapture while workers are alive.
- Face A always writes `hole_positions_cam0.json` … Face F `cam5.json`. Not the USB index.
- There is **no Admin and no PIN** in the UI. `capture_profile.json` still has an unused `admin_pin` field (`2468`). Do not build a PIN screen again.
- Camera setup is **after manifold selection**, cameras still closed, **once**. Skip when `config/camera_port_map.json` exists and `config/last_session.json` has `"setup_complete": true`.
- **Redo camera setup** is on the start screen (Sequential / Manual). It forces the setup page on the next manifold choice. It does not open cameras.
- Live bar is START / STOP / PAUSE / RESUME / OVERRIDE / Start screen. Start screen closes USB and relaunches so setup can run again. No setup buttons on the live bar.

## Operator flow

1. Sequential or Manual.
2. Manifold (skipped if only one model).
3. Camera setup, only the first time or after Redo:
   - Assign camera faces (required before Continue). Scan USB one at a time, pick A–F, Save.
   - Place hole ROIs (optional). One camera, freeze at capture-profile size, drag, Save, release.
   - Hole connections (optional). Type-in table or Load spreadsheet `.xlsx` / `.csv`. Dry-run, then Confirm writes `connectivity_rules.json` and a `.bak`.
4. Continue → six cameras open → START.

Every later shift: mode → manifold if needed → live → START.

## Excel ingest (workbook not in the repo yet)

The owner will supply the spreadsheet later. Do not invent hole geometry or a fake workbook.

Linked path (no loose ends):

- `src/connectivity_rules_io.py` — parse xlsx/csv, header aliases, hole-id normalize (`SEC_P_P`, `CENTRE_HOLE`, output faces like `C_F`), merge rows into rules, diff, atomic save.
- `src/rule_editor_ui.py` — Hole connections dialog. Load spreadsheet. Not PIN-gated.
- `requirements.txt` — `openpyxl`.
- `src/config_loader.py` — `hole_ids_for_face` and `save_rules` delegate to the io module.
- Dashboard camera-setup page button **Hole connections** opens `RuleEditorDialog` for the manifold just selected.
- `NAMING_CONVENTION.md` — hole ids in ROI `name` must match rule `hole_id` or every step fails.

Existing data, do not delete unless asked: `config/DALIA/connectivity_rules.json` (74 rules), `hole_positions_cam0`–`cam4` with circles, `cam5` (Face F) empty. Inspection will not start if the rules file is missing or empty. Face F empty does not bring setup back.

## History that must not be redone

- Six cameras display on Windows after MJPG 320×240 @ 5 fps, no YUY2, 90s handshake, hub interleave. USB5 ignored FPS until software pace. Sleep-between-reads froze tiles. Face A reconnect can come back YUY2; do not “fix” that by raising resolution.
- In-app ROI must not steal USB from live workers. Setup-page ROI opens one index, grabs a warmed frame, releases. That replaced the idea of editing on the live tiles.
- Admin was tried on the live bar, then on the start screen. Both are discarded. The owner could not calibrate while cameras were held, and did not want a PIN.
- First-launch assign wizard **before** mode was removed. Assign happens after the manifold.
- A sibling agent added Excel/type-in hole connections. Keep it. Do not drop `connectivity_rules_io.py` or `rule_editor_ui.py`.
- QCheckBox was missing on `FaceAssignWizardDialog` and crashed first zip launch (`f7c3ea1`). Keep the import.
- Do not commit `graphify-out/`, `SYSTEM_AUDIT.md`, or `image002.png` unless asked.
- Old branch `feat/in-app-camera-face-pipeline` stays at `a7a110e`. Do not move it.
- SSH push to `git@github.com:athsxx/Blob.git` failed before; HTTPS via `gh` worked. Do not force-push.

## Files

- `src/dashboard.py` — start, manifold, camera setup page, live.
- `src/camera_setup_ui.py` — face wizard and lab `CalibrateRoiDialog` (not on the operator path). No `AdminCaptureDialog`.
- `src/roi_editor.py` — `grab_setup_snapshot` + `RoiEditorDialog(setup_mode=True)`.
- `src/main.py` — does not open the face wizard before the start screen. Resolves USB indices after Continue when the port map exists.
- `src/camera_worker.py` — frozen capture. `snapshot` / `reload_rois` exist; setup ROI does not need them.
- `config/capture_profile.json` — 320×240, 5 fps, MJPG. No UI editor anymore.

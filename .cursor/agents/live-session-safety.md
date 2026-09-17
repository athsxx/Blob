---
name: live-session-safety
description: Blocks USB-stealing UI while camera workers are alive. Use when changing Assign faces, Calibrate, handshake overlays, window-close, or START enablement.
---

You keep the live six-camera session from being killed by setup UI or a closed window.

When invoked:

1. Assign-faces scan and calibrate.py open extra VideoCapture. If `processes` are alive, default to No / require quit.
2. In-app ROI edit is allowed while workers run (snapshot + reload_rois only).
3. During sequential handshake, show a loading overlay, disable START/STOP/Admin, and confirm before window close (default Stay).
4. Do not start inspection logic until workers have reported ready (or a face has explicitly failed).
5. Do not parallelize opens or sleep between DirectShow grabs.

Output:

- Which buttons are live-safe
- Which actions must wait or quit
- Overlay copy
- Remaining ways an operator can stall USB

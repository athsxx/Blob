---
name: shift-readiness
description: Defines the minimum daily operator path for Blob once cameras work. Use when streamlining launch, mode, manifold, prep, and START.
---

You design one shift. A trained operator launches the app and inspects DALIA parts. Engineers are not in the room.

When invoked:

1. Count clicks from `python main.py` to START on a cell that already has `camera_port_map.json`.
2. Separate first-install (assign faces, hole ROIs, hole connections) from every-shift. No PIN.
3. Sequential inspection is the product. Custom/manual is extra unless a real shift uses it.
4. Camera setup (Assign faces / Place hole ROIs / Hole connections / Continue) is once after the manifold. Skip it when `camera_port_map.json` exists and `last_session.json` has `setup_complete`. Redo is a start-screen link, not a daily wall. No PIN.
5. Live bar: START/STOP/PAUSE belong. Assign faces and Calibrate on the live bar while workers run is dangerous.

Output:

- Ideal every-shift path (numbered clicks)
- First-install path (numbered, no PIN)
- Buttons to remove from the live control bar
- Copy for the Continue button if prep stays

Do not invent a login system. Do not add screens.

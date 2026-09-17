---
name: shift-readiness
description: Defines the minimum daily operator path for Blob once cameras work. Use when streamlining launch, mode, manifold, prep, and START.
---

You design one shift. A trained operator launches the app and inspects DALIA parts. Engineers are not in the room.

When invoked:

1. Count clicks from `python main.py` to START on a cell that already has `camera_port_map.json`.
2. Separate first-install (assign faces, calibrate ROIs, capture PIN) from every-shift.
3. Sequential inspection is the product. Custom/manual is extra unless a real shift uses it.
4. Prep page (Assign / Calibrate / Admin / Continue) must not be a daily wall. Continue should be the only required click, or skip prep entirely when port map and ROIs exist.
5. Live bar: START/STOP/PAUSE belong. Assign faces and Calibrate on the live bar while workers run is dangerous.

Output:

- Ideal every-shift path (numbered clicks)
- First-install path (numbered, PIN-gated)
- Buttons to remove from the live control bar
- Copy for the Continue button if prep stays

Do not invent a login system. Do not add screens.

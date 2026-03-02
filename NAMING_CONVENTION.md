# Naming convention: ROIs and rules must match

The **logic engine** understands connectivity only when **hole IDs are identical** everywhere:

- **Hole position configs** (`hole_positions_camN.json`, or `config/rois_webcam.json`): each ROI has a `name` (or `hole_id`) that the camera worker sends in detection results.
- **Connectivity rules** (`connectivity_rules.json`): each rule uses `input.hole_id` and `expected_outputs[].hole_id`.
- **Global state** in the logic engine uses keys `Face_HoleID` (e.g. `A_A1`, `B_SEC_M_M`).

If the config says `M-M` and the rule says `SEC_M_M`, the state key is `B_M-M` but the rule looks for `B_SEC_M_M` → **no match**, so the rule always fails.

## Rule

**Use the same hole ID string in:**

1. `hole_positions_camN.json` (or equivalent ROI config) — `name` / `hole_id`
2. `connectivity_rules.json` — `input.hole_id` and every `expected_outputs[].hole_id`

When generating rules from the Excel (or any source), normalize to one canonical naming (e.g. `SEC_M_M`, `A1`, `CENTRE_HOLE`) and use that **exact** string in both the ROI configs and the rules.

## Current alignment

- **Face B (cam3):** Config uses `SEC_M_M`, `SEC_N_N`, `SEC_Z_Z`, `SEC_T_T` (aligned with rules).
- **Face A (cam2):** Config includes `A1`, `A7`, `A26`, `A15`, `A18`, `A14`, `A20` (rules use the same; Ø4-prefix holes excluded from config for now).
- **Input face “A-F” / “C-F” in Excel:** Means diagonal hole position; use the **first face** (A or C) as the single input face when generating rules.

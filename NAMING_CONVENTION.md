# Naming convention: ROIs and rules must match

The **logic engine** understands connectivity only when **hole IDs are identical** everywhere:

- **Hole position configs** (`hole_positions_camN.json`): each ROI has a `name` (or `hole_id`) that the camera worker sends in detection results. Face A = `cam0` … Face F = `cam5` (face ordinal, not USB index).
- **Connectivity rules** (`connectivity_rules.json`): each rule uses `input.hole_id` and `expected_outputs[].hole_id`.
- **Global state** in the logic engine uses keys `Face_HoleID` (e.g. `A_A1`, `B_SEC_M_M`).

If the config says `M-M` and the rule says `SEC_M_M`, the state key is `B_M-M` but the rule looks for `B_SEC_M_M` → **no match**, so the rule always fails.

## Rule

**Use the same hole ID string in:**

1. `hole_positions_camN.json` — `name` / `hole_id`
2. `connectivity_rules.json` — `input.hole_id` and every `expected_outputs[].hole_id`

When generating rules from Excel (or typing Hole connections on camera setup), normalize to one canonical naming (e.g. `SEC_M_M`, `A1`, `CENTRE_HOLE`) and use that **exact** string in both the ROI configs and the rules.

Inspection order is **derived** from the rules (`LogicEngine.build_guided_sequence`). There is no `inspection_sequences.json` file.

## Excel / type-in normalize table

| Spreadsheet / typed value | Stored as |
|---|---|
| Input or output face `A-F`, `C-F`, `A-E`, `B-C` | `A_F`, `C_F`, `A_E`, `B_C` (one hole, either camera) |
| Output face `B or D`, `B/D` | `B_OR_D` |
| `SEC P-P`, `SEC-P-P`, `P-P` | `SEC_P_P` |
| `M-M` | `SEC_M_M` |
| `N-N` / `Z-Z` / `T-T` / `JK-JK` | `SEC_N_N` / `SEC_Z_Z` / `SEC_T_T` / `SEC_JK_JK` |
| `ø4` / `Ø4` | `Ø4…` (keep Ø, same as current JSON) |
| One spreadsheet row = one insert | The same insert listed twice with the same exits stays one rule |

When an exit list is shorter than the hole list, the last face covers the remaining holes. When the face list is longer, the last hole is visible on each of those faces.

Camera setup path: after the manifold, **Hole connections**. Load spreadsheet (`.xlsx` / `.csv`) shows a dry-run diff; Confirm writes `config/<manifold>/connectivity_rules.json` (backup `.bak`). The DALIA workbook is `config/DALIA/dalia_manifold_inspection.xlsx`. Do not edit hole connections while START is running. There is no Admin PIN.

## Current alignment

Hole ROI files `hole_positions_cam0.json` … `cam5.json` are empty until ellipses are placed on the shop floor. Face A is still `cam0` and Face F is still `cam5`. Draw each name exactly as it appears in `connectivity_rules.json`.

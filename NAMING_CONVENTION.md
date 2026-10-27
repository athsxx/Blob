# Naming convention: ROIs and rules must match

The **logic engine** understands connectivity only when **hole IDs are identical** everywhere:

- **Hole position configs** (`hole_positions_camN.json`): each ROI has a `name` (or `hole_id`) that the camera worker sends in detection results. Face A = `cam0` … Face F = `cam5` (face ordinal, not USB index).
- **Connectivity rules** (`connectivity_rules.json`): each rule uses `input.hole_id` and `expected_outputs[].hole_id`.
- **Global state** in the logic engine uses keys `Face_HoleID` (e.g. `A_A1`, `B_SEC. M-M`).

If the ellipse says `M-M` and the rule says `SEC. M-M`, the state key is `B_M-M` but the rule looks for `B_SEC. M-M` → **no match**, so the rule always fails.

## Rule

**Use the same hole ID string in:**

1. `hole_positions_camN.json` — `name` / `hole_id`
2. `connectivity_rules.json` — `input.hole_id` and every `expected_outputs[].hole_id`

When generating rules from Excel (or typing Hole connections on camera setup), normalize to the sheet's words and use that **exact** string in both the ROI configs and the rules. Sections are `SEC. T1-T1`: the letters SEC, a full stop, a space, then the section. `SEC. T1-T1` is not `SEC. T2-T2` and is not a generic `T-T`.

Inspection order is **derived** from the rules (`LogicEngine.build_guided_sequence`). There is no `inspection_sequences.json` file.

## Excel / type-in normalize table

| Spreadsheet / typed value | Stored as |
|---|---|
| Input or output face `A-F`, `F-A`, `C-F`, `F-C`, `A-E`, `B-C` | `A_F`, `C_F`, `A_E`, `B_C` (one hole, either camera) |
| Output face `B or D`, `B/D` | `B_OR_D` |
| `Sec. P-P`, `SEC. P - P`, `P-P` | `SEC. P-P` |
| `Sec. M-M`, `M-M` | `SEC. M-M` |
| `Sec. M-M (COUNTER)` | `SEC. M-M COUNTER` |
| `M1-M1`, `Sec. M1-M1` | `SEC. M1-M1` |
| `SEC. N-N`, `SEC. N1-N1`, `SEC. JK-JK` | those names, with `SEC.` and no extra spaces |
| `SEC. T1-T1`, `SEC. T2-T2`, `SEC. T3-T3 COUNTER`, `SEC. T4-T4 COUNTER` | those names. They are not folded into `T-T` |
| `SEC. T4-T4 COUNTER` on the row that lights `SEC. P-P` | `SEC. T-T CENTRE` |
| `SEC. T-T CENTRE COUNTER` | `SEC. T-T CENTRE` |
| `SEC. Z1-Z1`, `SEC. Z2-Z2`, `SEC. Z3-Z3 COUNTER`, `SEC. Z-Z CENTRE` | those names |
| `Sec. Z-Z COUNTER`, `Sec. Z1-Z1 COUNTER` | `SEC. Z4-Z4 COUNTER` |
| `CENTRE HOLE (ANGULAR)` plus `(Oblong Hole)` | `CENTRE HOLE` |
| `Ø9.14 (SR. NO. 426) - A` | `Ø9.14 (SR. NO. 426 - A)` |
| Face C `Ø4 (OVAL HOLE)` | `Ø4 (OVAL HOLE) (SR. NO. 1079)` |
| `STRIGHT HOLE (LE-LE)` | `STRIGHT HOLE (LE-LE)` |
| A row whose insert says `LENGTH`, or whose inspection starts `HOLE OPEN` | not a rule |
| One spreadsheet row = one insert | The same insert listed twice with the same exits stays one rule |

When an exit list is shorter than the hole list, the last face covers the remaining holes. When the face list is longer, the last hole is visible on each of those faces.

Camera setup path: after the manifold, **Hole connections**. Load spreadsheet (`.xlsx` / `.csv`) shows a dry-run diff; Confirm writes `config/<manifold>/connectivity_rules.json` (backup `.bak`). The DALIA workbook is `config/DALIA/dalia_manifold_inspection.xlsx`. Do not edit hole connections while START is running. There is no Admin PIN.

## Current alignment

Hole ROI files `hole_positions_cam0.json` … `cam5.json` are empty until ellipses are placed on the shop floor. Face A is still `cam0` and Face F is still `cam5`. Draw each name exactly as it appears in `connectivity_rules.json`.

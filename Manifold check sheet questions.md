# DALIA sheet — naming interview

Source of truth: `Manifold check sheet final.xlsx`, sheet `HOLE OPEN`, saved 27 Oct 2026.

This file replaces the earlier question list. Answer under each question. A short “yes” is enough when the reading is right. Write the correction on the next line when it is not.

---

## What I think the job is

One name for each hole, used in three places with the same characters:

1. This sheet (after a spelling clean-up).
2. `config/DALIA/connectivity_rules.json` — the rulebook the app actually runs.
3. The hole ellipses, when the shop floor draws them. The ellipse name has to be the rulebook name or the step never passes.

The clean-up is small and strict:

- ALL CAPS.
- A section hole always starts with `SEC.` (the letters SEC, then a full stop, then a space).
- `Sec.`, `SEC` with no full stop, and a bare `M1-M1` are the same kind of mistake. They become `SEC.`
- Numbered sections stay numbered. `SEC. T1-T1` is not `SEC. T2-T2` and is not a generic `T-T`.
- The **Mock Up** column is not part of this. `OK`, `MANUAL`, `NEED CHECK`, `reverse`, camera notes — ignored.

Today the rulebook does the opposite of that. It folds `T1`, `T2`, and `T-T` into one id `SEC_T_T`, and folds the Z holes into one id `SEC_Z_Z`. That fold goes away.

I will not edit the JSON until you answer this file.

---

## Locked unless you cross them out

1. Mock Up is ignored.
2. A rule is one connection row. **Insert Rod** plus the first **View** is where the rod goes in. **For Inspection** plus the second **View** is what must light.
3. A row whose Insert Rod says `LENGTH`, and a row whose inspection cell starts `HOLE OPEN -`, is a shop note. It is not a rule and it is not a hole name. The note `HOLE OPEN - SEC. T-T` does not create a hole called `T-T`.
4. Row 48, `(Oblong Hole)`, is the rest of the name on row 47, not its own rule.
5. Face letters stay A–F. `C-F`, `A-F`, `A-E`, and `B-C` are one hole both cameras can see. `B Or D` means either camera is enough.
6. Timing stays 250 ms and 3 stable frames. Logic stays AND: every listed exit has to light.

---

## 1. The exact characters we store

The app can store either of these. They are not the same string, so the ellipse and the rule must pick one.

| | Example for the T1 section | Example for centre |
| --- | --- | --- |
| Sheet form | `SEC. T1-T1` | `CENTRE HOLE` |
| Today’s rulebook form | `SEC_T1_T1` | `CENTRE_HOLE` |

**Q1.** Store the sheet form: `SEC. T1-T1`, with the full stop, the space, and the hyphen. ALL CAPS. Same characters on the ellipse. Yes?

Answer: YES

---

## 2. One spelling for every section

These are the same hole written more than one way. I will keep the right-hand name everywhere.

| Written on the sheet as | Stored as |
| --- | --- |
| `SEC. N-N`, `Sec. N-N` | `SEC. N-N` |
| `SEC. N1-N1`, `Sec. N1-N1` | `SEC. N1-N1` |
| `SEC. M1-M1`, `Sec. M1-M1`, and the bare `M1-M1` on the B1 row | `SEC. M1-M1` |
| `SEC. M-M`, `Sec. M-M` | `SEC. M-M` |
| `SEC. P-P`, `Sec. P-P`, `Sec. P - P` | `SEC. P-P` |
| `SEC. JK-JK`, `Sec. JK-JK` | `SEC. JK-JK` |
| `SEC. T3-T3 COUNTER`, `Sec. T3-T3 COUNTER`, `SEC T3-T3 COUNTER` | `SEC. T3-T3 COUNTER` |

**Q2.** That table is right. Yes?

Answer: YES

**Q3.** `Sec. M-M (COUNTER)` is a different hole from `SEC. M-M`. I will store it as `SEC. M-M COUNTER`. Yes?

Answer: YES,  but it may overlap sec. m-m. sec  mm is a sention inside which the counter is present. 
 
---

## 3. Sections the sheet numbers, and must not be merged

Each line below is its own hole. Say if any two lines are actually the same hole.

### T

- `SEC. T1-T1` — exit of the Ø4 round hole on face A
- `SEC. T2-T2` — exit of the Ø4 oval on face A, and of the angular hole
- `SEC. T3-T3 COUNTER` — its own insert, and an exit of B19 and of B16
- `SEC. T4-T4 COUNTER` — two connection rows, both inserts on B
- `SEC. T-T CENTRE COUNTER` — exit of B11. The length note under it says `SEC. T-T COUNTER`. I am treating that note as this same hole, not a sixth T hole. treat is as SEC. T-T CENTRE COUNTER only. 

**Q4.** Those five T names are five different holes. Yes?

Answer:YES

**Q5.** The two `SEC. T4-T4 COUNTER` rows are two passages of the same hole: one lights `SEC. P-P` on C, one lights `B11` on E. Two rules, one hole name. Yes?

Answer: No, the Sec p-p one, name it as SEC. T-T CENTRE. so we'll have 5 sec tts. 

### Z

- `SEC. Z-Z CENTRE` — exit of B1. Sheet spelling is `Centre`.
- `SEC. Z1-Z1` — exit of the Ø4 oval on C, and of the straight hole
- `SEC. Z1-Z1 COUNTER` — exit of B7, written `Sec. Z1-Z1 COUNTER`
- `SEC. Z2-Z2` — exit of the Ø4 round hole on C. The length note says `SEC. Z-Z`. That note is not a separate hole.
- `SEC. Z3-Z3 COUNTER` — its own insert, and an exit of B2
- `SEC. Z4-Z4 COUNTER` — exit of B3. The length note says `SEC. Z-Z COUNTER`.
- `SEC. Z-Z COUNTER` — its own insert on B, lights B7 on D. Written `Sec. Z-Z COUNTER`.

**Q6.** Those seven Z names are seven different holes. Yes?

Answer:no, the last one , SEC. Z-Z COUNTER` — its own insert on B, lights B7 on D. Written `Sec. Z-Z COUNTER` here we'll replace the Z-Z counter as SEC. Z4-Z4 COUNTER, because we dont have a simple z-z counter, we have named all with numbers like z1, to z4

**Q7.** If `SEC. Z-Z COUNTER` is really one of the numbered Z holes, which number? If it is its own hole, write “its own”.

Answer:

**Q8.** `SEC. Z1-Z1` and `SEC. Z1-Z1 COUNTER` are different holes. Yes?

Answer: ichekc above answer. 

---

## 4. Names that are not sections

Same rule: one ALL CAPS string, no second spelling.

| I will store | Also written as | Same hole? |
| --- | --- | --- |
| `CENTRE HOLE` | `CENTRE HOLE` | one hole per face. Face B’s centre is not face D’s centre. The face letter keeps them apart. |
| `CENTRE HOLE (ANGULAR) (OBLONG HOLE)` | row 47 `CENTRE HOLE (ANGULAR)` plus row 48 `(Oblong Hole)`. The length note says `CENTRE HOLE-Oblong Hole`. | one hole, on B, lights A24 on C |
| `Ø9.14 (SR. NO. 426 - A)` | insert is written `Ø9.14 (SR. NO. 426) - A` (the hyphen sits outside the bracket). Exits are written `Ø9.14 (SR. NO. 426 - A)`. | I will use the exit spelling |
| `Ø9.14 (SR. NO. 426 - B)` | only the exit spelling appears | its own hole |
| `Ø5.61 (SR. NO. 474)` | sheet has `Sr. No.` | capitals only |
| `Ø12.32 (SR. NO. 324)` | already this | keep |
| `Ø4 (ROUND HOLE)` | face A and face C both use this name | same words, two holes, split by face |
| `Ø4 (OVAL HOLE) (SR. NO. 978)` | face A insert, and the angular-hole exit | one hole on A |
| `Ø4 (OVAL HOLE) (SR. NO. 1079)` | face C insert is only `Ø4 (OVAL HOLE)`. The straight-hole exit adds the serial. | one hole on C. I will use the serial form |
| `Ø6.5 (SR. NO. 1185) LD-LD` | | its own hole |
| `Ø6.5 (SR. NO. 1188) LE-LE` | | its own hole |
| `ANGULAR HOLE (LD-LD)` | sheet breaks the line and has spaces inside the brackets | one hole |
| `STRIGHT HOLE (LE-LE)` | sheet spelling is `STRIGHT`, not `STRAIGHT` | I will keep `STRIGHT` so it matches the sheet |
| `MIDDLE AT B5-B6` | | keep |

**Q9.** That table is right, including keeping the misspelling `STRIGHT`. Yes?

Answer:

**Q10.** `CENTRE HOLE (ANGULAR) (OBLONG HOLE)` is a different hole from `CENTRE HOLE` on face B. Yes?

Answer: they'er the same, like oblomng hole is inside centre hole. so we can change that accordingly, as in overlap rois, or we'll ideate asomething 

---

## 5. What I change after you answer

No code until this list is accepted.

1. Copy this workbook to `config/DALIA/dalia_manifold_inspection.xlsx`.
2. Rebuild `config/DALIA/connectivity_rules.json` from the connection rows only, with the names you locked above.
3. Stop the importer from folding `T1` / `T2` / `Z1` / `Z2` into a generic `T-T` or `Z-Z`.
4. Update `NAMING_CONVENTION.md` so the stored name is the ALL CAPS `SEC.` form, not `SEC_T_T`.
5. Leave the hole ellipse files empty. Nobody invents pixel positions. The shop floor draws ellipses under these names.

**Q11.** That is the whole change. Yes? Write here if something in that list must wait.

Answer: flag the ones which will overlap like i mentioned. the new excel, i'll check everything again from scratch which you make

---

## Checked reading

Accepted as written: Q1, Q2, Q4, and the six locked items. The JSON waits. The next file is a cleaned workbook you review from scratch.

### Names that changed

| Sheet text | Stored name | Why |
| --- | --- | --- |
| `SEC. T4-T4 COUNTER` on B that lights `SEC. P-P` on C | `SEC. T-T CENTRE` | Q5. This row is not T4. |
| `SEC. T4-T4 COUNTER` on B that lights `B11` on E | `SEC. T4-T4 COUNTER` | The other T4 row stays. |
| Exit of B11 written `SEC. T-T CENTRE COUNTER` | `SEC. T-T CENTRE` | Same hole as the row above. One name. The word COUNTER is not part of it. |
| Insert `Sec. Z-Z COUNTER` on B that lights B7 on D | `SEC. Z4-Z4 COUNTER` | Q6. No unnumbered Z counter. |
| Exit of B7 written `Sec. Z1-Z1 COUNTER` | `SEC. Z4-Z4 COUNTER` | Q8. The connection stays B7 → B3 and this section. The section name was wrong. |
| `CENTRE HOLE (ANGULAR)` plus `(Oblong Hole)` | `CENTRE HOLE` | Q10. The oblong is inside the centre hole. |
| `Sec. M-M (COUNTER)` | `SEC. M-M COUNTER` | Q3. Own name. |

`SEC. Z1-Z1` stays. Only the COUNTER spelling on the B7 row moves to Z4. “Z4-z4” is the existing name `SEC. Z4-Z4 COUNTER`, the same hole B3 lights.

Five T holes:

1. `SEC. T1-T1`
2. `SEC. T2-T2`
3. `SEC. T3-T3 COUNTER`
4. `SEC. T4-T4 COUNTER`
5. `SEC. T-T CENTRE`

Five Z holes:

1. `SEC. Z-Z CENTRE`
2. `SEC. Z1-Z1`
3. `SEC. Z2-Z2`
4. `SEC. Z3-Z3 COUNTER`
5. `SEC. Z4-Z4 COUNTER`

### Overlaps to flag on the cleaned sheet

Separate names. The ellipse work comes later. The flag only marks that one hole sits inside the other.

| Inside | Section |
| --- | --- |
| `SEC. M-M COUNTER` | `SEC. M-M` |
| Oblong, stored as `CENTRE HOLE` | `CENTRE HOLE` on that face |

### Q9 locked

Yes. Non-section holes keep the sheet’s words, including `STRIGHT`. One stored spelling where the sheet wrote the same hole twice:

- `Ø9.14 (SR. NO. 426) - A` and `Ø9.14 (SR. NO. 426 - A)` → `Ø9.14 (SR. NO. 426 - A)`
- Face C insert `Ø4 (OVAL HOLE)` and the straight-hole exit `Ø4 (OVAL HOLE) (SR. NO. 1079)` → `Ø4 (OVAL HOLE) (SR. NO. 1079)`

`CENTRE HOLE (ANGULAR)` plus `(Oblong Hole)` stays `CENTRE HOLE` (Q10).

The RULES sheet was accepted. `config/DALIA/connectivity_rules.json` is rebuilt from these 74 connections. The ellipse files were not rewritten. 



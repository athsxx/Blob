"""
Normalize, validate, merge, diff, and save connectivity_rules.json.

The DALIA inspection workbook is the HOLE OPEN sheet: Insert Rod, View,
For Inspection, View. Length rows and the Mock Up column are shop notes.
A hyphenated face such as C-F is one hole visible on both cameras. Hole
ids keep the sheet's words: ALL CAPS, sections as ``SEC. T1-T1``. Both
the type-in editor and the spreadsheet path write the same JSON contract
that LogicEngine.load_rules already understands.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from logic_engine import parse_face_to_faces, rule_has_unavailable_output

VALID_FACES = frozenset("ABCDEF")
DEFAULT_LOGIC = "AND"
DEFAULT_TIMING = {"max_delay_ms": 250, "min_stable_frames": 3}
OUTPUT_FACE_CHOICES = [
    "A", "B", "C", "D", "E", "F",
    "C_F", "A_F", "A_E", "A___E", "B_C", "B_OR_D",
]

# Section body after "SEC." is removed and spaces around hyphens are closed.
# Numbered sections stay numbered. Generic T-T and Z-Z are not holes.
_SECTION_BODY = {
    "M-M": "SEC. M-M",
    "M-M COUNTER": "SEC. M-M COUNTER",
    "M1-M1": "SEC. M1-M1",
    "N-N": "SEC. N-N",
    "N1-N1": "SEC. N1-N1",
    "P-P": "SEC. P-P",
    "JK-JK": "SEC. JK-JK",
    "T1-T1": "SEC. T1-T1",
    "T2-T2": "SEC. T2-T2",
    "T3-T3 COUNTER": "SEC. T3-T3 COUNTER",
    "T4-T4 COUNTER": "SEC. T4-T4 COUNTER",
    "T-T CENTRE": "SEC. T-T CENTRE",
    "T-T CENTRE COUNTER": "SEC. T-T CENTRE",
    "Z-Z CENTRE": "SEC. Z-Z CENTRE",
    "Z1-Z1": "SEC. Z1-Z1",
    "Z1-Z1 COUNTER": "SEC. Z4-Z4 COUNTER",
    "Z2-Z2": "SEC. Z2-Z2",
    "Z3-Z3 COUNTER": "SEC. Z3-Z3 COUNTER",
    "Z4-Z4 COUNTER": "SEC. Z4-Z4 COUNTER",
    "Z-Z COUNTER": "SEC. Z4-Z4 COUNTER",
}

# Older rule files used underscores. These map onto the sheet form.
# SEC_T_T and SEC_Z_Z are absent on purpose: they collapsed distinct holes.
_LEGACY_HOLE_IDS = {
    "SEC_M_M": "SEC. M-M",
    "M_M": "SEC. M-M",
    "SEC_M_M_COUNTER": "SEC. M-M COUNTER",
    "SEC_M1_M1": "SEC. M1-M1",
    "M1_M1": "SEC. M1-M1",
    "SEC_N_N": "SEC. N-N",
    "N_N": "SEC. N-N",
    "SEC_N1_N1": "SEC. N1-N1",
    "N1_N1": "SEC. N1-N1",
    "SEC_P_P": "SEC. P-P",
    "P_P": "SEC. P-P",
    "SEC_JK_JK": "SEC. JK-JK",
    "JK_JK": "SEC. JK-JK",
    "SEC_T1_T1": "SEC. T1-T1",
    "SEC_T2_T2": "SEC. T2-T2",
    "SEC_T3_T3_COUNTER": "SEC. T3-T3 COUNTER",
    "SEC_T4_T4_COUNTER": "SEC. T4-T4 COUNTER",
    "SEC_T_T_CENTRE": "SEC. T-T CENTRE",
    "SEC_T_T_CENTRE_COUNTER": "SEC. T-T CENTRE",
    "SEC_Z_Z_CENTRE": "SEC. Z-Z CENTRE",
    "SEC_Z1_Z1": "SEC. Z1-Z1",
    "SEC_Z1_Z1_COUNTER": "SEC. Z4-Z4 COUNTER",
    "SEC_Z2_Z2": "SEC. Z2-Z2",
    "SEC_Z3_Z3_COUNTER": "SEC. Z3-Z3 COUNTER",
    "SEC_Z4_Z4_COUNTER": "SEC. Z4-Z4 COUNTER",
    "SEC_Z_Z_COUNTER": "SEC. Z4-Z4 COUNTER",
    "CENTRE_HOLE": "CENTRE HOLE",
    "CENTER_HOLE": "CENTRE HOLE",
}

# F-C and C-F are the same pair of cameras. Store one token.
_FACE_PAIR = {
    frozenset(("A", "E")): "A_E",
    frozenset(("A", "F")): "A_F",
    frozenset(("B", "C")): "B_C",
    frozenset(("C", "F")): "C_F",
}

_HEADER_ALIASES = {
    "input_face": {
        "input face", "from face", "laser face", "laser in face",
        "input_face", "face", "a-f",
        "input view (flashlight)", "input view",
        "insert face", "insert view",
    },
    "input_hole": {
        "input hole", "from hole", "laser hole", "laser in hole",
        "input_hole", "hole", "section", "hole id", "input hole id",
        "insert rod / passlight", "insert rod", "passlight",
        "insert hole",
    },
    "output_face": {
        "output face", "to face", "exit face", "light face",
        "output_face", "light should appear face",
        "output view (lightbulb)", "output view",
        "light-out face", "light out face",
    },
    "output_hole": {
        "output hole", "to hole", "exit hole", "light hole",
        "output_hole", "light should appear hole", "output hole id",
        "open to check (for inspection)", "open to check",
        "for inspection",
        "light-out hole", "light out hole",
    },
    "execution": {"manual", "execution", "manual check"},
    "logic": {"logic", "and/or", "and or"},
    "mandatory": {"mandatory", "required"},
}

_NUMBERED_FACE = re.compile(
    r"^(?:output|light(?:-out)?|light out)\s*([0-9]+)\s*face$"
)
_NUMBERED_HOLE = re.compile(
    r"^(?:output|light(?:-out)?|light out)\s*([0-9]+)\s*hole$"
)


@dataclass
class ConnectionRow:
    input_face: str
    input_hole: str
    output_face: str
    output_hole: str
    mandatory: bool = True
    logic: str = DEFAULT_LOGIC
    source_row: Optional[int] = None
    execution: str = "auto"


@dataclass
class SpreadsheetParse:
    headers: List[str] = field(default_factory=list)
    mapped: Dict[str, int] = field(default_factory=dict)
    extra_outputs: List[Tuple[int, int, int]] = field(default_factory=list)  # (n, face_col, hole_col)
    rows: List[ConnectionRow] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    skipped_title_rows: int = 0
    source_row_count: int = 0


@dataclass
class RulesDiff:
    added: List[str]
    removed: List[str]
    changed: List[str]
    unchanged: int
    merged_from_rows: int
    duplicate_ids_in_old: List[str]
    unknown_holes: List[Tuple[str, str]]
    guided_before: int
    guided_after: int
    old_count: int
    new_count: int
    manual_count: int = 0
    roi_renames: List[Tuple[str, str, str]] = field(default_factory=list)
    roi_drops: List[Tuple[str, str]] = field(default_factory=list)

    def is_noop(self) -> bool:
        return not self.added and not self.removed and not self.changed


@dataclass
class RoiAlignPlan:
    renamed: List[Tuple[str, str, str]] = field(default_factory=list)
    dropped: List[Tuple[str, str]] = field(default_factory=list)
    names_after: Dict[str, Set[str]] = field(default_factory=dict)
    writes: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def normalize_hole_id(raw: Any) -> str:
    """Sheet form. Sections are ``SEC. T1-T1``. ``T1`` does not become ``T-T``."""
    text = _nfc(raw).strip()
    if not text:
        return ""
    text = text.replace("ø", "Ø").replace("Ø".lower(), "Ø")
    text = text.replace("phi", "Ø").replace("PHI", "Ø")
    text = " ".join(text.replace("\n", " ").split())
    text = text.upper()
    text = re.sub(r"\(\s*", "(", text)
    text = re.sub(r"\s*\)", ")", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace("Ø9.14 (SR. NO. 426) - A", "Ø9.14 (SR. NO. 426 - A)")
    if text == "Ø4 (OVAL HOLE)":
        text = "Ø4 (OVAL HOLE) (SR. NO. 1079)"
    if text in {"CENTRE HOLE (ANGULAR)", "CENTRE HOLE (ANGULAR) (OBLONG HOLE)"}:
        text = "CENTRE HOLE"
    elif "OBLONG" in text and "CENTRE HOLE" in text:
        text = "CENTRE HOLE"
    if text in _LEGACY_HOLE_IDS:
        return _LEGACY_HOLE_IDS[text]
    body = re.sub(r"^SEC\.?\s*", "", text)
    body = re.sub(r"\s*-\s*", "-", body)
    body = re.sub(r"\s+", " ", body).strip()
    body = body.replace("(COUNTER)", "COUNTER")
    body = re.sub(r"\s+", " ", body).strip()
    if body in _SECTION_BODY:
        return _SECTION_BODY[body]
    return text


def _is_shop_note(hole: str, out_hole: str) -> bool:
    """Length and HOLE OPEN rows are shop notes, not connections."""
    hole_u = _nfc(hole).upper()
    out_u = _nfc(out_hole).strip().upper()
    if re.search(r"\bLENGTH\b", hole_u):
        return True
    return out_u.startswith("HOLE OPEN")


def _insert_for_passage(insert: str, exit_holes: Sequence[str]) -> str:
    """The T4 row that lights SEC. P-P is SEC. T-T CENTRE, not a second T4."""
    if (
        insert == "SEC. T4-T4 COUNTER"
        and "SEC. P-P" in exit_holes
        and "B11" not in exit_holes
    ):
        return "SEC. T-T CENTRE"
    return insert


def normalize_input_face(raw: Any) -> str:
    """A-F / C-F is one hole visible on both cameras, same form as an output face."""
    return normalize_output_face(raw)


def normalize_output_face(raw: Any) -> str:
    text = _nfc(raw).strip().upper()
    if not text:
        return ""
    compact = re.sub(r"\s+", " ", text)
    if compact in OUTPUT_FACE_CHOICES or compact in VALID_FACES:
        return compact
    if " OR " in f" {compact} " or "/OR/" in compact.replace(" ", ""):
        letters = [ch for ch in compact if ch in VALID_FACES]
        if len(letters) >= 2:
            return f"{letters[0]}_OR_{letters[1]}"
    sep = compact.replace(" ", "").replace("/", "-").replace("_OR_", "-")
    if "-" in sep:
        letters = [p for p in sep.split("-") if p in VALID_FACES]
        if len(letters) == 1:
            return letters[0]
        if len(letters) >= 2:
            pair = _FACE_PAIR.get(frozenset(letters[:2]))
            if pair:
                return pair
            known = f"{letters[0]}_{letters[1]}"
            or_form = f"{letters[0]}_OR_{letters[1]}"
            if known in OUTPUT_FACE_CHOICES:
                return known
            if or_form in OUTPUT_FACE_CHOICES:
                return or_form
            return known
    letters = [ch for ch in compact if ch in VALID_FACES]
    if len(letters) == 1:
        return letters[0]
    parsed = parse_face_to_faces(compact.replace("-", "_").replace("/", "_"))
    if parsed:
        if compact.replace(" ", "") in OUTPUT_FACE_CHOICES:
            return compact.replace(" ", "")
        if len(parsed) == 1:
            return parsed[0]
        return "_".join(parsed)
    return compact.replace("-", "_").replace("/", "_").replace(" ", "_")


def make_rule_id(face: str, hole_id: str) -> str:
    return f"FACE_{face}_{hole_id}"


def split_cell_list(raw: Any) -> List[str]:
    """Split a cell on commas that are not inside parentheses."""
    text = _nfc(raw).strip()
    if not text:
        return []
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
        else:
            buf.append(ch)
    part = "".join(buf).strip()
    if part:
        parts.append(part)
    return parts


def _join_faces(faces: Sequence[str]) -> str:
    letters: List[str] = []
    for face in faces:
        for letter in parse_face_to_faces(normalize_output_face(face)) or []:
            if letter not in letters:
                letters.append(letter)
    if not letters:
        return ""
    if len(letters) == 1:
        return letters[0]
    return "-".join(letters)


def pair_exit_holes_and_faces(
    holes: Sequence[str], faces: Sequence[str]
) -> List[Tuple[str, str]]:
    """Pair exits from the left.

    Extra holes stay on the last face. Extra faces mean the last hole is
    visible on each of those faces.
    """
    hole_list = [h for h in holes if str(h).strip()]
    face_list = [f for f in faces if str(f).strip()]
    if not hole_list or not face_list:
        return []
    if len(hole_list) == len(face_list):
        return list(zip(hole_list, face_list))
    if len(hole_list) > len(face_list):
        head = len(face_list) - 1
        paired = list(zip(hole_list[:head], face_list[:head]))
        last_face = face_list[-1]
        paired.extend((hole, last_face) for hole in hole_list[head:])
        return paired
    head = len(hole_list) - 1
    paired = list(zip(hole_list[:head], face_list[:head]))
    paired.append((hole_list[-1], _join_faces(face_list[head:])))
    return paired


def _truthy(raw: Any) -> bool:
    if raw is None or raw is True:
        return True
    if raw is False:
        return False
    text = str(raw).strip().lower()
    if text in {"", "1", "true", "yes", "y", "mandatory", "required"}:
        return True
    if text in {"0", "false", "no", "n", "optional"}:
        return False
    return True


def _logic(raw: Any) -> str:
    text = str(raw or DEFAULT_LOGIC).strip().upper()
    return "OR" if text == "OR" else DEFAULT_LOGIC


def normalize_execution(raw: Any) -> str:
    """``manual`` is an operator Pass/Fail with no timer. Anything else is automatic."""
    text = str(raw or "").strip().lower()
    if text in {"manual", "yes", "y", "true", "1", "x"}:
        return "manual"
    return "auto"


def canonical_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    inp = rule.get("input") or {}
    face = normalize_input_face(inp.get("face", ""))
    hole = normalize_hole_id(inp.get("hole_id", ""))
    outputs: List[Dict[str, Any]] = []
    seen = set()
    for out in rule.get("expected_outputs") or []:
        oface = normalize_output_face(out.get("face", ""))
        ohole = normalize_hole_id(out.get("hole_id", ""))
        key = (oface, ohole)
        if not oface or not ohole or key in seen:
            continue
        seen.add(key)
        outputs.append({
            "face": oface,
            "hole_id": ohole,
            "mandatory": bool(out.get("mandatory", True)),
        })
    timing = rule.get("timing") or {}
    return {
        "rule_id": str(rule.get("rule_id") or make_rule_id(face, hole)),
        "input": {"face": face, "hole_id": hole},
        "expected_outputs": outputs,
        "logic": _logic(rule.get("logic")),
        "execution": normalize_execution(rule.get("execution")),
        "timing": {
            "max_delay_ms": int(timing.get("max_delay_ms") or DEFAULT_TIMING["max_delay_ms"]),
            "min_stable_frames": int(
                timing.get("min_stable_frames") or DEFAULT_TIMING["min_stable_frames"]
            ),
        },
    }


def merge_connection_rows(rows: Sequence[ConnectionRow]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    for row in rows:
        face = normalize_input_face(row.input_face)
        hole = normalize_hole_id(row.input_hole)
        oface = normalize_output_face(row.output_face)
        ohole = normalize_hole_id(row.output_hole)
        if not face or not hole or not oface or not ohole:
            continue
        key = (face, hole)
        if key not in grouped:
            grouped[key] = {
                "rule_id": make_rule_id(face, hole),
                "input": {"face": face, "hole_id": hole},
                "expected_outputs": [],
                "logic": _logic(row.logic),
                "execution": normalize_execution(row.execution),
                "timing": dict(DEFAULT_TIMING),
            }
            order.append(key)
        elif normalize_execution(row.execution) == "manual":
            grouped[key]["execution"] = "manual"
        outs = grouped[key]["expected_outputs"]
        seen = {(o["face"], o["hole_id"]) for o in outs}
        if (oface, ohole) not in seen:
            outs.append({
                "face": oface,
                "hole_id": ohole,
                "mandatory": bool(row.mandatory),
            })
        if row.logic:
            grouped[key]["logic"] = _logic(row.logic)
    rules = [grouped[k] for k in order]
    return uniquify_rule_ids(rules)


def rules_to_connection_rows(rules: Sequence[Dict[str, Any]]) -> List[ConnectionRow]:
    rows: List[ConnectionRow] = []
    for rule in rules or []:
        canon = canonical_rule(rule)
        inp = canon["input"]
        logic = canon["logic"]
        outputs = canon["expected_outputs"] or [
            {"face": "", "hole_id": "", "mandatory": True}
        ]
        for out in outputs:
            rows.append(ConnectionRow(
                input_face=inp["face"],
                input_hole=inp["hole_id"],
                output_face=out.get("face", ""),
                output_hole=out.get("hole_id", ""),
                mandatory=bool(out.get("mandatory", True)),
                logic=logic,
                execution=canon["execution"],
            ))
    return rows


def uniquify_rule_ids(rules: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One rule_id per rule. Same input hole already merged; suffix only on true collisions."""
    used: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for rule in rules:
        canon = canonical_rule(rule)
        rid = canon["rule_id"] or make_rule_id(
            canon["input"]["face"], canon["input"]["hole_id"]
        )
        n = used.get(rid, 0)
        if n:
            canon["rule_id"] = f"{rid}_{n + 1}"
        used[rid] = n + 1
        out.append(canon)
    return out


def duplicate_rule_ids(rules: Sequence[Dict[str, Any]]) -> List[str]:
    counts: Dict[str, int] = {}
    for rule in rules or []:
        rid = str(rule.get("rule_id") or "")
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    return [rid for rid, n in counts.items() if n > 1]


def validate_rules(rules: Sequence[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    seen_ids: Set[str] = set()
    for i, raw in enumerate(rules or [], start=1):
        rule = canonical_rule(raw)
        rid = rule["rule_id"]
        face = rule["input"]["face"]
        hole = rule["input"]["hole_id"]
        if not parse_face_to_faces(face):
            errors.append(f"Rule {i} ({rid}): laser face must be A–F, got {face!r}")
        if not hole:
            errors.append(f"Rule {i} ({rid}): laser hole is empty")
        if rid in seen_ids:
            errors.append(f"Rule {i}: duplicate id {rid}")
        seen_ids.add(rid)
        if not rule["expected_outputs"]:
            errors.append(f"Rule {i} ({rid}): no light-out holes")
        for out in rule["expected_outputs"]:
            parsed = parse_face_to_faces(out["face"])
            if not parsed:
                errors.append(
                    f"Rule {i} ({rid}): cannot read light face {out['face']!r}"
                )
            if not out["hole_id"]:
                errors.append(f"Rule {i} ({rid}): empty light hole")
        if rule["logic"] not in {"AND", "OR"}:
            errors.append(f"Rule {i} ({rid}): logic must be AND or OR")
    return errors


def hole_ids_for_face(rules: Sequence[Dict[str, Any]], face: str) -> List[str]:
    """Unique hole_ids that appear as input or expected output on this face."""
    want = str(face).strip().upper()
    names: List[str] = []
    seen: Set[str] = set()
    for rule in rules or []:
        inp = rule.get("input") or {}
        if want in parse_face_to_faces(str(inp.get("face", ""))):
            hid = str(inp.get("hole_id") or "").strip()
            if hid and hid not in seen:
                seen.add(hid)
                names.append(hid)
        for out in rule.get("expected_outputs") or []:
            faces = parse_face_to_faces(str(out.get("face", "")))
            if want not in faces:
                continue
            hid = str(out.get("hole_id") or "").strip()
            if hid and hid not in seen:
                seen.add(hid)
                names.append(hid)
    return names


def roi_names_by_face(config_dir: str, folder: str) -> Dict[str, Set[str]]:
    from config_loader import face_roi_basename

    names: Dict[str, Set[str]] = {f: set() for f in "ABCDEF"}
    for face in "ABCDEF":
        path = os.path.join(config_dir, folder, face_roi_basename(face))
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for circle in data.get("circles") or []:
            hid = str(circle.get("name") or circle.get("hole_id") or "").strip()
            if hid:
                names[face].add(hid)
    return names


def _fold_hole_key(name: str) -> str:
    text = _nfc(name).upper().replace("ø", "Ø")
    text = re.sub(r"[^0-9A-ZØ]+", " ", text)
    return " ".join(text.split())


def _hole_tokens(name: str) -> Set[str]:
    return set(_fold_hole_key(name).split())


def map_roi_name_to_sheet(old: str, sheet_names: Sequence[str]) -> Optional[str]:
    """One sheet name for an old ellipse label, or None if it is not unique."""
    names = [str(n).strip() for n in sheet_names if str(n).strip()]
    old = str(old or "").strip()
    if not old:
        return None
    if old in names:
        return old
    legacy = _LEGACY_HOLE_IDS.get(old) or _LEGACY_HOLE_IDS.get(old.upper())
    if legacy and legacy in names:
        return legacy
    normalized = normalize_hole_id(old)
    if normalized and normalized in names:
        return normalized
    folded = _fold_hole_key(old)
    fold_hits = [n for n in names if _fold_hole_key(n) == folded]
    if len(fold_hits) == 1:
        return fold_hits[0]
    old_tokens = _hole_tokens(old)
    if not old_tokens:
        return None
    subset_hits = [n for n in names if old_tokens <= _hole_tokens(n)]
    if len(subset_hits) == 1:
        return subset_hits[0]
    return None


def _align_circles_for_face(
    circles: Sequence[Dict[str, Any]],
    sheet_names: Sequence[str],
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], List[str]]:
    sheet = [n for n in dict.fromkeys(str(s).strip() for s in sheet_names) if n]
    taken: Set[str] = set()
    kept: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for circle in circles or []:
        if not isinstance(circle, dict):
            continue
        name = str(circle.get("name") or circle.get("hole_id") or "").strip()
        if name in sheet and name not in taken:
            taken.add(name)
            kept.append(dict(circle))
        else:
            pending.append(dict(circle))
    remaining = [n for n in sheet if n not in taken]
    renamed: List[Tuple[str, str]] = []
    dropped: List[str] = []
    for circle in pending:
        name = str(circle.get("name") or circle.get("hole_id") or "").strip()
        target = map_roi_name_to_sheet(name, remaining)
        if not target or target in taken:
            if name:
                dropped.append(name)
            continue
        circle["name"] = target
        if "hole_id" in circle:
            circle["hole_id"] = target
        kept.append(circle)
        taken.add(target)
        remaining = [n for n in remaining if n != target]
        if target != name:
            renamed.append((name, target))
    return kept, renamed, dropped


def plan_roi_alignment(
    config_dir: str,
    folder: str,
    rules: Sequence[Dict[str, Any]],
) -> RoiAlignPlan:
    from config_loader import face_roi_basename

    plan = RoiAlignPlan(names_after={f: set() for f in "ABCDEF"})
    for face in "ABCDEF":
        path = os.path.join(config_dir, folder, face_roi_basename(face))
        sheet = hole_ids_for_face(rules, face)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        circles = data.get("circles") or []
        if not isinstance(circles, list):
            circles = []
        kept, renamed, dropped = _align_circles_for_face(circles, sheet)
        payload = dict(data)
        payload["circles"] = kept
        plan.writes.append((os.path.abspath(path), payload))
        plan.names_after[face] = {
            str(c.get("name") or c.get("hole_id") or "").strip()
            for c in kept
            if str(c.get("name") or c.get("hole_id") or "").strip()
        }
        for old, new in renamed:
            plan.renamed.append((face, old, new))
        for old in dropped:
            plan.dropped.append((face, old))
    return plan


def apply_roi_alignment(plan: RoiAlignPlan) -> None:
    for path, payload in plan.writes or []:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="rois_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def unknown_holes_vs_rois(
    rules: Sequence[Dict[str, Any]],
    roi_names: Dict[str, Set[str]],
) -> List[Tuple[str, str]]:
    missing: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    known_rules = {f: set(hole_ids_for_face(rules, f)) for f in "ABCDEF"}
    for face in "ABCDEF":
        for hid in sorted(known_rules[face]):
            rois = roi_names.get(face) or set()
            if hid in rois:
                continue
            # Excel-normalized name vs a spaced ROI label
            aliases = {hid, hid.replace("_", " "), hid.replace("_", "-")}
            if any(a in rois for a in aliases):
                continue
            key = (face, hid)
            if key not in seen:
                seen.add(key)
                missing.append(key)
    return missing


def guided_step_count(
    rules: Sequence[Dict[str, Any]],
    available_faces: Optional[Set[str]] = None,
) -> int:
    faces = available_faces if available_faces is not None else set("ABCDEF")
    seen: Set[str] = set()
    n = 0
    for rule in rules or []:
        rid = str(rule.get("rule_id") or "")
        if not rid or rid in seen:
            continue
        if rule_has_unavailable_output(rule, faces):
            continue
        input_faces = parse_face_to_faces(str((rule.get("input") or {}).get("face", "")))
        if input_faces and all(f not in faces for f in input_faces):
            continue
        seen.add(rid)
        n += 1
    return n


def _input_key(rule: Dict[str, Any]) -> Tuple[str, str]:
    inp = (rule.get("input") or {})
    return (str(inp.get("face") or ""), str(inp.get("hole_id") or ""))


def _index_by_input(rules: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """One entry per laser-in hole; later duplicate rule_ids merge their outputs."""
    indexed: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for rule in rules or []:
        canon = canonical_rule(rule)
        key = _input_key(canon)
        if not key[0] or not key[1]:
            continue
        if key not in indexed:
            indexed[key] = canon
            continue
        existing = indexed[key]
        if canon.get("execution") == "manual":
            existing["execution"] = "manual"
        seen = {(o["face"], o["hole_id"]) for o in existing["expected_outputs"]}
        for out in canon["expected_outputs"]:
            t = (out["face"], out["hole_id"])
            if t not in seen:
                existing["expected_outputs"].append(out)
                seen.add(t)
    return indexed


def _outputs_key(rule: Dict[str, Any]) -> Tuple:
    outs = tuple(sorted(
        (o["face"], o["hole_id"], bool(o.get("mandatory", True)))
        for o in rule.get("expected_outputs") or []
    ))
    return (rule.get("logic"), normalize_execution(rule.get("execution")), outs)


def diff_rules(
    old_rules: Sequence[Dict[str, Any]],
    new_rules: Sequence[Dict[str, Any]],
    merged_from_rows: int = 0,
    roi_names: Optional[Dict[str, Set[str]]] = None,
    available_faces: Optional[Set[str]] = None,
) -> RulesDiff:
    old_idx = _index_by_input(old_rules)
    new_idx = _index_by_input(new_rules)
    added = sorted(
        new_idx[k]["rule_id"] for k in new_idx if k not in old_idx
    )
    removed = sorted(
        old_idx[k]["rule_id"] for k in old_idx if k not in new_idx
    )
    changed = sorted(
        new_idx[k]["rule_id"]
        for k in new_idx
        if k in old_idx and _outputs_key(new_idx[k]) != _outputs_key(old_idx[k])
    )
    unknown = unknown_holes_vs_rois(new_rules, roi_names or {})
    return RulesDiff(
        added=added,
        removed=removed,
        changed=changed,
        unchanged=len(new_idx) - len(added) - len(changed),
        merged_from_rows=merged_from_rows,
        duplicate_ids_in_old=duplicate_rule_ids(old_rules),
        unknown_holes=unknown,
        guided_before=guided_step_count(old_rules, available_faces),
        guided_after=guided_step_count(new_rules, available_faces),
        old_count=len(list(old_rules or [])),
        new_count=len(new_idx),
        manual_count=sum(
            1 for rule in new_idx.values() if rule.get("execution") == "manual"
        ),
        roi_renames=[],
        roi_drops=[],
    )


def format_diff(diff: RulesDiff) -> str:
    lines = [
        f"This replaces {diff.old_count} working rules with {diff.new_count} unique connections.",
        f"Guided steps now: {diff.guided_after} (was {diff.guided_before}).",
        (
            f"Manual checks: {diff.manual_count}. "
            "They run after the automatic holes. Pass or Fail, no timer."
        ),
    ]
    if diff.merged_from_rows:
        lines.append(
            f"Spreadsheet rows merged: {diff.merged_from_rows} → {diff.new_count} rules."
        )
    if diff.duplicate_ids_in_old:
        lines.append(
            "Duplicate ids in the current file that merge on save: "
            + ", ".join(diff.duplicate_ids_in_old)
        )
    lines.append(f"Added ({len(diff.added)}): " + (", ".join(diff.added) or "none"))
    lines.append(f"Removed ({len(diff.removed)}): " + (", ".join(diff.removed) or "none"))
    lines.append(f"Changed ({len(diff.changed)}): " + (", ".join(diff.changed) or "none"))
    if diff.roi_renames:
        lines.append("")
        lines.append("Rings renamed to sheet names:")
        for face, old, new in diff.roi_renames[:40]:
            lines.append(f"  Face {face}: {old} → {new}")
        if len(diff.roi_renames) > 40:
            lines.append(f"  … {len(diff.roi_renames) - 40} more")
    if diff.roi_drops:
        lines.append("")
        lines.append("Rings dropped (not on this sheet face):")
        for face, old in diff.roi_drops[:40]:
            lines.append(f"  Face {face}: {old}")
        if len(diff.roi_drops) > 40:
            lines.append(f"  … {len(diff.roi_drops) - 40} more")
    if diff.unknown_holes:
        lines.append("")
        lines.append("Hole names with no matching ellipse on the face picture:")
        for face, hid in diff.unknown_holes[:40]:
            lines.append(f"  Face {face}: {hid}")
        if len(diff.unknown_holes) > 40:
            lines.append(f"  … {len(diff.unknown_holes) - 40} more")
        lines.append(
            "Those names must match the labels on the face pictures. "
            "If they do not match, every check will fail. "
            "Place missing ellipses with Place hole ROIs on the camera setup page."
        )
    lines.append("")
    lines.append("Timing in the file is stored only. PASS/FAIL still uses the 2 second window.")
    return "\n".join(lines)


def save_rules_atomic(path: str, rules: Sequence[Dict[str, Any]], backup: bool = True) -> str:
    errors = validate_rules(rules)
    if errors:
        raise ValueError("\n".join(errors))
    payload = {"rules": uniquify_rule_ids(rules)}
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if backup and os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    fd, tmp = tempfile.mkstemp(prefix="rules_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def load_rules_file(path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    rules = data.get("rules") or []
    return list(rules) if isinstance(rules, list) else []


def _norm_header(text: Any) -> str:
    return re.sub(r"\s+", " ", _nfc(text).strip().lower())


def _map_headers(headers: Sequence[str]) -> Tuple[Dict[str, int], List[Tuple[int, int, int]]]:
    mapped: Dict[str, int] = {}
    extras: Dict[int, Dict[str, int]] = {}
    for i, raw in enumerate(headers):
        h = _norm_header(raw)
        if not h:
            continue
        matched_alias = False
        for field_name, aliases in _HEADER_ALIASES.items():
            if h in aliases and field_name not in mapped:
                mapped[field_name] = i
                matched_alias = True
                break
        if matched_alias:
            continue
        if h == "view":
            if "input_face" not in mapped:
                mapped["input_face"] = i
            elif "output_face" not in mapped:
                mapped["output_face"] = i
            continue
        mface = _NUMBERED_FACE.match(h)
        mhole = _NUMBERED_HOLE.match(h)
        if mface:
            n = int(mface.group(1))
            if n == 1 and "output_face" not in mapped:
                mapped["output_face"] = i
            else:
                extras.setdefault(n, {})["face"] = i
        if mhole:
            n = int(mhole.group(1))
            if n == 1 and "output_hole" not in mapped:
                mapped["output_hole"] = i
            else:
                extras.setdefault(n, {})["hole"] = i
    extra_pairs = [
        (n, cols["face"], cols["hole"])
        for n, cols in sorted(extras.items())
        if "face" in cols and "hole" in cols
    ]
    return mapped, extra_pairs


def _cell(row: Sequence[Any], index: Optional[int]) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    val = row[index]
    if val is None:
        return ""
    return str(val).strip()


def _rows_from_table(headers: Sequence[str], data_rows: Sequence[Sequence[Any]]) -> SpreadsheetParse:
    parsed = SpreadsheetParse(headers=[str(h) for h in headers])
    mapped, extras = _map_headers(headers)
    parsed.mapped = mapped
    parsed.extra_outputs = extras
    needed = {"input_face", "input_hole", "output_face", "output_hole"}
    if not needed.issubset(mapped):
        missing = sorted(needed - set(mapped))
        parsed.errors.append(
            "Could not map spreadsheet columns ("
            + ", ".join(missing)
            + "). Headers found: "
            + ", ".join(h for h in parsed.headers if str(h).strip())
            + ". Share the workbook so these headers can be bound."
        )
        return parsed
    last_face = ""
    last_hole = ""
    for n, row in enumerate(data_rows, start=1):
        if not any(_cell(row, i) for i in range(len(row))):
            continue
        parsed.source_row_count += 1
        raw_face = _cell(row, mapped["input_face"])
        raw_hole = _cell(row, mapped["input_hole"])
        raw_out_face = _cell(row, mapped["output_face"])
        raw_out_hole = _cell(row, mapped["output_hole"])
        mandatory = _truthy(_cell(row, mapped.get("mandatory"))) if "mandatory" in mapped else True
        logic = _logic(_cell(row, mapped.get("logic"))) if "logic" in mapped else DEFAULT_LOGIC
        execution = (
            normalize_execution(_cell(row, mapped["execution"]))
            if "execution" in mapped
            else "auto"
        )
        extra_exits: List[Tuple[str, str]] = []
        for light_n, fcol, hcol in extras:
            oface = _cell(row, fcol)
            ohole = _cell(row, hcol)
            if oface and ohole:
                extra_exits.extend(pair_exit_holes_and_faces(
                    split_cell_list(ohole),
                    split_cell_list(oface),
                ))
            elif oface or ohole:
                parsed.errors.append(
                    f"Row {n}: Light {light_n} needs both a hole and a face"
                )
        if not raw_face and not raw_hole and not raw_out_face and not raw_out_hole and not extra_exits:
            continue
        if _is_shop_note(raw_hole, raw_out_hole):
            continue
        if not raw_hole and raw_out_hole.strip().upper() in {"OPEN TO CHECK", "FOR INSPECTION"}:
            continue
        inserts = split_cell_list(raw_hole)
        exits = pair_exit_holes_and_faces(
            split_cell_list(raw_out_hole),
            split_cell_list(raw_out_face),
        )
        if len(inserts) > 1:
            parsed.errors.append(
                f"Row {n}: held ({raw_hole or 'blank insert'} → {raw_out_hole})"
            )
            continue
        if len(inserts) == 1:
            last_hole = inserts[0]
            if raw_face:
                last_face = raw_face
            if not exits and not extra_exits:
                continue
        elif exits:
            if not last_hole:
                parsed.errors.append(
                    f"Row {n}: light-out hole has no insert hole above it"
                )
                continue
            inserts = [last_hole]
            if not raw_face:
                raw_face = last_face
        else:
            parsed.errors.append(
                f"Row {n}: held ({raw_hole or 'blank insert'} → {raw_out_hole})"
            )
            continue
        input_face = raw_face
        exit_pairs = list(exits) + extra_exits
        input_hole = _insert_for_passage(
            normalize_hole_id(inserts[0]),
            [normalize_hole_id(hole) for hole, _face in exit_pairs],
        )
        for hole, face in exit_pairs:
            parsed.rows.append(ConnectionRow(
                input_face=input_face,
                input_hole=input_hole,
                output_face=face,
                output_hole=hole,
                mandatory=mandatory,
                logic=logic,
                source_row=n,
                execution=execution,
            ))
    return parsed


def _find_header_row(rows: Sequence[Sequence[Any]]) -> Tuple[int, List[str]]:
    best_i = 0
    best_score = -1
    best_headers: List[str] = []
    for i, row in enumerate(rows[:15]):
        headers = [str(c) if c is not None else "" for c in row]
        mapped, extras = _map_headers(headers)
        score = len(mapped) + len(extras)
        if score > best_score:
            best_score = score
            best_i = i
            best_headers = headers
    return best_i, best_headers


def parse_csv_file(path: str) -> SpreadsheetParse:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = [list(r) for r in reader]
    if not rows:
        parsed = SpreadsheetParse()
        parsed.errors.append("Spreadsheet is empty.")
        return parsed
    header_i, headers = _find_header_row(rows)
    parsed = _rows_from_table(headers, rows[header_i + 1 :])
    parsed.skipped_title_rows = header_i
    return parsed


def parse_xlsx_file(path: str) -> SpreadsheetParse:
    try:
        import openpyxl
    except ImportError as exc:
        parsed = SpreadsheetParse()
        parsed.errors.append(
            "openpyxl is not installed. pip install openpyxl  — or Save As CSV and load that."
        )
        parsed.errors.append(str(exc))
        return parsed
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = None
    for name in wb.sheetnames:
        if name.strip().lower() in {
            "rules", "connectivity", "hole connections", "connections", "hole open",
        }:
            sheet = wb[name]
            break
    if sheet is None:
        sheet = wb.active
    rows = []
    for row in sheet.iter_rows(values_only=True):
        rows.append([c if c is not None else "" for c in row])
    wb.close()
    if not rows:
        parsed = SpreadsheetParse()
        parsed.errors.append("Spreadsheet is empty.")
        return parsed
    header_i, headers = _find_header_row(rows)
    parsed = _rows_from_table(headers, rows[header_i + 1 :])
    parsed.skipped_title_rows = header_i
    return parsed


def _sheet_face(face: str) -> str:
    text = str(face or "")
    if "_OR_" in text:
        return text.replace("_OR_", " or ")
    return text.replace("_", "-")


def inspection_rows_from_rules(rules: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """One row per insert, in the same columns as the inspection sheet."""
    rows: List[Dict[str, str]] = []
    for rule in uniquify_rule_ids(rules or []):
        canon = canonical_rule(rule)
        insert = canon["input"]["hole_id"]
        if not insert:
            continue
        holes = [str(out.get("hole_id") or "") for out in canon["expected_outputs"]]
        faces = [_sheet_face(str(out.get("face") or "")) for out in canon["expected_outputs"]]
        rows.append({
            "manual": "YES" if canon["execution"] == "manual" else "",
            "insert": insert,
            "insert_view": _sheet_face(canon["input"]["face"]),
            "inspection": ", ".join(hole for hole in holes if hole),
            "exit_view": ", ".join(face for face in faces if face),
        })
    return rows


def write_connections_workbook(path: str, rules: Sequence[Dict[str, Any]]) -> str:
    """The inspection sheet: one row per insert, Manual, Insert Rod, View, For Inspection, View."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is not installed. pip install openpyxl"
        ) from exc

    headers = ["Manual", "Insert Rod", "View", "For Inspection", "View"]
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "HOLE OPEN"
    sheet.append(headers)
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri")
    thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    wrap = Alignment(wrap_text=True, vertical="center")
    for col in range(1, len(headers) + 1):
        cell = sheet.cell(1, col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin
    sheet.row_dimensions[1].height = 22
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    manual_fill = PatternFill("solid", fgColor="FCE4D6")
    for row_i, item in enumerate(inspection_rows_from_rules(rules), start=2):
        values = [
            item["manual"],
            item["insert"],
            item["insert_view"],
            item["inspection"],
            item["exit_view"],
        ]
        sheet.append(values)
        for col in range(1, len(headers) + 1):
            cell = sheet.cell(row_i, col)
            cell.border = thin
            cell.alignment = wrap
            cell.font = Font(name="Calibri", size=11)
        if item["manual"] == "YES":
            sheet.cell(row_i, 1).fill = manual_fill

    widths = [12, 36, 16, 54, 18]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    how = wb.create_sheet("HOW TO FILL")
    how["A1"] = "Standard manifold inspection sheet"
    how["A1"].font = Font(bold=True, size=16, name="Calibri")
    lines = [
        "Use the HOLE OPEN sheet. One row is one hole the rod goes into.",
        "Insert Rod is the hole name. The first View is the camera face (A, or C-F when both cameras see it).",
        "For Inspection lists every hole that must light, separated by commas.",
        "The second View lists the face for each of those holes, in the same order, separated by commas.",
        "If one face covers every hole in the list, write that face once.",
        "Manual: write YES to run that hole at the end. The operator presses Pass or Fail. There is no timer.",
        "Leave Manual blank and the cameras decide.",
        "Do not add LENGTH rows or a Mock Up column. Those are not rules.",
        "Section holes are written SEC. T1-T1 — SEC, a full stop, a space, then the section. ALL CAPS.",
        "Example: Insert Rod A14, View A-F, For Inspection SEC. M-M, A13, View B, B.",
        "A new manifold starts from a blank copy of this workbook plus an empty rules file.",
        "In the app: Hole connections, Load spreadsheet, tick Manual where needed, then Save.",
    ]
    for index, line in enumerate(lines, start=3):
        how.cell(index, 1, line)
        how.cell(index, 1).font = Font(name="Calibri", size=12)
        how.cell(index, 1).alignment = Alignment(wrap_text=True, vertical="center")
    how.column_dimensions["A"].width = 120

    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    wb.save(path)
    return path


def write_tree_workbook(path: str, rules: Sequence[Dict[str, Any]]) -> str:
    """Older name. Writes the one-row sheet."""
    return write_connections_workbook(path, rules)


def parse_spreadsheet(path: str) -> SpreadsheetParse:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".xlsx", ".xlsm"}:
        return parse_xlsx_file(path)
    if ext in {".csv", ".txt"}:
        return parse_csv_file(path)
    parsed = SpreadsheetParse()
    parsed.errors.append(f"Unsupported file type {ext}. Use .xlsx or .csv.")
    return parsed


def without_conflicting_inputs(
    rows: Sequence[ConnectionRow],
) -> Tuple[List[ConnectionRow], List[str]]:
    """Drop an insert whose sheet gives two different comma lists.

    A tree row is one light-out hole. Those rows combine. A conflict is the
    same insert written twice with two different multi-hole lists.
    """
    by_key: Dict[Tuple[str, str], Dict[int, Set[Tuple[str, str]]]] = {}
    for row in rows:
        key = (normalize_input_face(row.input_face), normalize_hole_id(row.input_hole))
        src = row.source_row if row.source_row is not None else id(row)
        by_key.setdefault(key, {}).setdefault(src, set()).add(
            (normalize_output_face(row.output_face), normalize_hole_id(row.output_hole))
        )
    blocked: Set[Tuple[str, str]] = set()
    notes: List[str] = []
    for key, sources in by_key.items():
        full_lists = {
            frozenset(exits) for exits in sources.values() if len(exits) > 1
        }
        if len(full_lists) > 1:
            blocked.add(key)
            notes.append(
                f"Held overlapping insert {key[0]} {key[1]} "
                f"({len(full_lists)} different exit lists)"
            )
    kept = [
        row for row in rows
        if (normalize_input_face(row.input_face), normalize_hole_id(row.input_hole)) not in blocked
    ]
    return kept, notes


def carry_manual_checks(
    previous: Sequence[Dict[str, Any]],
    incoming: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Keep a manual mark when the same insert face and hole are still present."""
    manual_keys = {
        (canon["input"]["face"], canon["input"]["hole_id"])
        for rule in previous or []
        for canon in [canonical_rule(rule)]
        if canon["execution"] == "manual" and canon["input"]["face"] and canon["input"]["hole_id"]
    }
    kept: List[Dict[str, Any]] = []
    for rule in incoming or []:
        canon = canonical_rule(rule)
        key = (canon["input"]["face"], canon["input"]["hole_id"])
        if key in manual_keys:
            canon["execution"] = "manual"
        kept.append(canon)
    return kept


def rules_from_spreadsheet(path: str) -> Tuple[List[Dict[str, Any]], SpreadsheetParse]:
    parsed = parse_spreadsheet(path)
    if parsed.errors and not parsed.rows:
        return [], parsed
    kept, notes = without_conflicting_inputs(parsed.rows)
    parsed.rows = kept
    parsed.errors.extend(notes)
    rules = merge_connection_rows(kept)
    return rules, parsed


INSPECTION_WORKBOOK_NAME = "manifold_inspection.xlsx"
TEMPLATE_DIR_NAME = "template"


def template_workbook_path(config_dir: str) -> str:
    return os.path.join(os.path.abspath(config_dir), TEMPLATE_DIR_NAME, INSPECTION_WORKBOOK_NAME)


def ensure_standard_template(config_dir: str) -> str:
    """The one blank HOLE OPEN workbook every new manifold is copied from."""
    path = template_workbook_path(config_dir)
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_connections_workbook(path, [])
    return path


def write_rules_from_workbook(workbook_path: str, rules_path: str) -> int:
    """Build connectivity_rules.json from an inspection sheet. The sheet is the source."""
    rules, parsed = rules_from_spreadsheet(workbook_path)
    blocking = [err for err in parsed.errors if parsed.rows or "Could not map" in err]
    if blocking and not rules:
        raise ValueError("\n".join(parsed.errors) or "The inspection sheet has no usable rows.")
    save_rules_atomic(rules_path, rules, backup=os.path.isfile(rules_path))
    return len(rules)


def inject_inspection_template(dest_dir: str, config_dir: str) -> int:
    """Copy the standard sheet into a manifold folder and write its rules file."""
    src = ensure_standard_template(config_dir)
    os.makedirs(dest_dir, exist_ok=True)
    dest_sheet = os.path.join(dest_dir, INSPECTION_WORKBOOK_NAME)
    shutil.copy2(src, dest_sheet)
    return write_rules_from_workbook(dest_sheet, os.path.join(dest_dir, "connectivity_rules.json"))

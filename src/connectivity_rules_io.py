"""
Normalize, validate, merge, diff, and save connectivity_rules.json.

The DALIA inspection workbook uses Insert / Input View / Open To Check /
Output View. A hyphenated face such as C-F is one hole visible on both
cameras. Both the type-in editor and the spreadsheet path write the same
JSON contract that LogicEngine.load_rules already understands.
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

# After spaces/hyphens → underscore. Keys are uppercased alias keys.
_HOLE_ALIASES = {
    "SEC_P_P": "SEC_P_P",
    "P_P": "SEC_P_P",
    "SEC_M_M": "SEC_M_M",
    "M_M": "SEC_M_M",
    "SEC_N_N": "SEC_N_N",
    "N_N": "SEC_N_N",
    "SEC_Z_Z": "SEC_Z_Z",
    "Z_Z": "SEC_Z_Z",
    "SEC_T_T": "SEC_T_T",
    "T_T": "SEC_T_T",
    "SEC_JK_JK": "SEC_JK_JK",
    "JK_JK": "SEC_JK_JK",
    "CENTRE_HOLE": "CENTRE_HOLE",
    "CENTER_HOLE": "CENTRE_HOLE",
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
        "light-out hole", "light out hole",
    },
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

    def is_noop(self) -> bool:
        return not self.added and not self.removed and not self.changed


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or ""))


def normalize_hole_id(raw: Any) -> str:
    text = _nfc(raw).strip()
    if not text:
        return ""
    text = text.replace("ø", "Ø").replace("Ø".lower(), "Ø")
    text = text.replace("phi", "Ø").replace("PHI", "Ø")
    alias_key = re.sub(r"[^A-Z0-9Ø]+", "_", text.upper())
    alias_key = re.sub(r"_+", "_", alias_key).strip("_")
    if alias_key in _HOLE_ALIASES:
        return _HOLE_ALIASES[alias_key]
    return alias_key


def is_unnamed_counter(raw: Any) -> bool:
    """Bare T-T and Z-Z counters are not one hole.

    A drilled-down name such as SEC. T-T CENTRE COUNTER or SEC. Z3-Z3 COUNTER
    is a real hole and is kept.
    """
    key = normalize_hole_id(raw)
    return key in {
        "T_T_COUNTER",
        "SEC_T_T_COUNTER",
        "Z_Z_COUNTER",
        "SEC_Z_Z_COUNTER",
    }


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
                "timing": dict(DEFAULT_TIMING),
            }
            order.append(key)
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
    return (rule.get("logic"), outs)


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
    )


def format_diff(diff: RulesDiff) -> str:
    lines = [
        f"This replaces {diff.old_count} working rules with {diff.new_count} unique connections.",
        f"Guided steps now: {diff.guided_after} (was {diff.guided_before}).",
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
        if is_unnamed_counter(inserts[0]) or any(
            is_unnamed_counter(hole) for hole, _face in list(exits) + extra_exits
        ):
            parsed.errors.append(
                f"Row {n}: held, unnamed counter ({inserts[0]})"
            )
            continue
        input_hole = inserts[0]
        input_face = raw_face
        for hole, face in list(exits) + extra_exits:
            parsed.rows.append(ConnectionRow(
                input_face=input_face,
                input_hole=input_hole,
                output_face=face,
                output_hole=hole,
                mandatory=mandatory,
                logic=logic,
                source_row=n,
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
        if name.strip().lower() in {"rules", "connectivity", "hole connections", "connections"}:
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


def write_connections_workbook(path: str, rules: Sequence[Dict[str, Any]]) -> str:
    """One row per insert hole. Each light-out hole is the next pair of columns."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError(
            "openpyxl is not installed. pip install openpyxl"
        ) from exc

    prepared: List[Tuple[Dict[str, str], List[Dict[str, Any]]]] = []
    widest = 1
    for rule in uniquify_rule_ids(rules):
        canon = canonical_rule(rule)
        inp = canon["input"]
        outputs = list(canon["expected_outputs"])
        if not inp.get("hole_id"):
            continue
        prepared.append((inp, outputs))
        widest = max(widest, len(outputs) or 1)
    pair_count = max(widest + 1, 4)

    headers = ["Insert hole", "Insert face"]
    for n in range(1, pair_count + 1):
        headers.extend([f"Light {n} hole", f"Light {n} face"])

    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "Hole connections"
    sheet.append(headers)
    insert_fill = PatternFill("solid", fgColor="0E6E86")
    light_fills = (
        PatternFill("solid", fgColor="8A5A12"),
        PatternFill("solid", fgColor="6E4A10"),
    )
    header_font = Font(bold=True, color="FFFFFF")
    thin = Border(
        left=Side(style="thin", color="E4DDD0"),
        right=Side(style="thin", color="E4DDD0"),
        top=Side(style="thin", color="E4DDD0"),
        bottom=Side(style="thin", color="E4DDD0"),
    )
    for col in range(1, len(headers) + 1):
        cell = sheet.cell(1, col)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin
        if col <= 2:
            cell.fill = insert_fill
        else:
            pair = (col - 3) // 2
            cell.fill = light_fills[pair % 2]
    sheet.row_dimensions[1].height = 32
    sheet.freeze_panes = "C2"
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}1"

    zebra = PatternFill("solid", fgColor="F7F4EE")
    for row_i, (inp, outputs) in enumerate(prepared, start=2):
        values: List[str] = [inp["hole_id"], _sheet_face(inp["face"])]
        for n in range(pair_count):
            if n < len(outputs):
                values.append(str(outputs[n].get("hole_id") or ""))
                values.append(_sheet_face(str(outputs[n].get("face") or "")))
            else:
                values.extend(["", ""])
        sheet.append(values)
        for col in range(1, len(headers) + 1):
            cell = sheet.cell(row_i, col)
            cell.border = thin
            cell.alignment = Alignment(vertical="center")
            if row_i % 2 == 0:
                cell.fill = zebra
            if col <= 2:
                cell.font = Font(bold=True)

    sheet.column_dimensions["A"].width = 28
    sheet.column_dimensions["B"].width = 14
    for col in range(3, len(headers) + 1):
        letter = get_column_letter(col)
        sheet.column_dimensions[letter].width = 28 if col % 2 == 1 else 14

    how = wb.create_sheet("How to fill")
    how["A1"] = "Hole connections"
    how["A1"].font = Font(bold=True, size=16)
    lines = [
        "Each row is one hole the laser goes into.",
        "Insert hole and Insert face name that hole and the camera that sees it.",
        "Light 1 hole and Light 1 face are the first place the light should appear.",
        "Light 2 is the next place, on the same row. Light 3 is the one after that.",
        "Leave a Light pair blank when you do not need it.",
        "A face is one letter, such as B. Use A-F or C-F when that hole is on both cameras.",
        "Type one hole name in each cell. Do not put several holes in one cell.",
        "Example: laser into A14 on A-F. Light appears at SEC_M_M on B, then at A13 on B.",
        "That row is: Insert hole A14, Insert face A-F, Light 1 hole SEC_M_M, Light 1 face B, Light 2 hole A13, Light 2 face B.",
        "Save this file, then in the app choose Load spreadsheet.",
    ]
    for i, line in enumerate(lines, start=3):
        how.cell(i, 1, line)
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


def rules_from_spreadsheet(path: str) -> Tuple[List[Dict[str, Any]], SpreadsheetParse]:
    parsed = parse_spreadsheet(path)
    if parsed.errors and not parsed.rows:
        return [], parsed
    kept, notes = without_conflicting_inputs(parsed.rows)
    parsed.rows = kept
    parsed.errors.extend(notes)
    rules = merge_connection_rows(kept)
    return rules, parsed

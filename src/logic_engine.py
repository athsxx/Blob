"""
Central Logic Engine

The "brain" of the inspection system. Aggregates detection results from all
cameras, evaluates connectivity rules, and produces PASS/FAIL decisions.

Key Responsibilities:
- Maintain global ROI state across all cameras
- Evaluate rules when input holes are activated
- Apply timing constraints (sustained detection window)
- Produce explainable PASS/FAIL results (one per activation)
"""

import time
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
from enum import Enum

# Single-face letters used in state keys (Face_HoleID)
VALID_FACES = frozenset("ABCDEF")

# Default sustained detection window (seconds)
DEFAULT_STABLE_WINDOW_S = 2.0


def parse_face_to_faces(face: str) -> List[str]:
    """
    Parse a face specifier into a list of single-face letters.
    Supports compound/alternative faces from connectivity_rules.json:
    - "C_F" -> ["C", "F"] (C or F)
    - "A_F" -> ["A", "F"]
    - "B_OR_D" -> ["B", "D"]
    - "A___E", "A_E" -> ["A", "E"]
    - "B_C" -> ["B", "C"]
    - "A" -> ["A"] (single face unchanged)
    """
    if not face:
        return []
    face = str(face).strip().upper()
    # Single face letter
    if len(face) == 1 and face in VALID_FACES:
        return [face]
    # Compound: split on underscore, keep only single-letter face tokens
    tokens = face.replace("_OR_", "_").split("_")
    return [t for t in tokens if len(t) == 1 and t in VALID_FACES]


class InspectionResult(Enum):
    """Possible inspection outcomes."""
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"
    ERROR = "ERROR"


class RuleState(Enum):
    """State machine states for per-rule tracking."""
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    DECIDED = "DECIDED"


@dataclass
class RuleEvaluationResult:
    """Result of evaluating a single connectivity rule."""
    rule_id: str
    result: InspectionResult
    input_hole: str           # Face_HoleID format (e.g., "A_A1")
    expected_outputs: List[str]
    detected_outputs: List[str]
    missing_outputs: List[str]
    evaluation_time_ms: float
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['result'] = self.result.value
        return result


@dataclass
class RuleTracker:
    """
    Per-rule state machine that tracks detection lifecycle.
    
    Lifecycle:
        IDLE --(input detected)--> MONITORING --(stable_window elapsed + all outputs)--> DECIDED(PASS)
                                        |
                                        +--(stable_window elapsed + missing outputs)--> DECIDED(FAIL)
                                        |
                                        +--(input lost for > grace period)--> IDLE (no log)
    """
    rule_id: str
    state: RuleState = RuleState.IDLE
    monitoring_start: float = 0.0        # time.time() when monitoring began
    stable_window_s: float = DEFAULT_STABLE_WINDOW_S
    grace_period_s: float = 0.5          # tolerate brief detection dropouts
    decision: Optional[InspectionResult] = None
    _last_seen_active: float = 0.0       # last time input was detected
    
    def start_monitoring(self):
        """Transition from IDLE to MONITORING."""
        self.state = RuleState.MONITORING
        self.monitoring_start = time.time()
        self._last_seen_active = time.time()
        self.decision = None
    
    def touch(self):
        """Mark input as still active (update last-seen time)."""
        self._last_seen_active = time.time()
    
    def input_lost_too_long(self, now: float) -> bool:
        """True if input has been absent longer than grace period."""
        return (now - self._last_seen_active) > self.grace_period_s
    
    def decide(self, result: InspectionResult):
        """Transition from MONITORING to DECIDED."""
        self.state = RuleState.DECIDED
        self.decision = result
    
    def reset(self):
        """Reset to IDLE."""
        self.state = RuleState.IDLE
        self.monitoring_start = 0.0
        self._last_seen_active = 0.0
        self.decision = None
    
    def elapsed_s(self) -> float:
        """Seconds elapsed since monitoring started."""
        if self.state == RuleState.MONITORING:
            return time.time() - self.monitoring_start
        return 0.0


@dataclass 
class GlobalState:
    """
    Tracks the current state of all ROIs across all cameras.
    Updated in real-time as detection results arrive.
    """
    # Current detection state: "Face_HoleID" -> bool
    roi_states: Dict[str, bool] = field(default_factory=dict)
    
    # Detection timestamps: "Face_HoleID" -> timestamp when first detected
    detection_times: Dict[str, float] = field(default_factory=dict)
    
    # Confidence values: "Face_HoleID" -> confidence (0.0-1.0)
    confidences: Dict[str, float] = field(default_factory=dict)
    
    # Camera health: "CAM_X" -> {"connected": bool, "fps": float}
    camera_health: Dict[str, Dict] = field(default_factory=dict)
    
    # Completed targets (for guided sequence): "Face_HoleID"
    completed_targets: Set[str] = field(default_factory=set)
    
    def update_from_detection(self, camera_result: Dict[str, Any]):
        """
        Update state from a camera worker's detection result.
        
        Args:
            camera_result: Dict with 'face', 'detections', 'health' keys
        """
        face = camera_result.get('face', 'X')
        camera_id = camera_result.get('camera_id', f'CAM_{face}')
        
        # Update camera health
        health = camera_result.get('health', {})
        self.camera_health[camera_id] = health
        
        # Update ROI states
        for det in camera_result.get('detections', []):
            hole_id = det.get('hole_id', '')
            roi_key = f"{face}_{hole_id}"
            
            is_detected = det.get('laser', False)
            confidence = det.get('confidence', 0.0)
            
            # Track state change
            was_detected = self.roi_states.get(roi_key, False)
            
            if is_detected and not was_detected:
                # New detection - record timestamp
                self.detection_times[roi_key] = time.time()
            elif not is_detected and was_detected:
                # Lost detection - clear timestamp
                self.detection_times.pop(roi_key, None)
            
            self.roi_states[roi_key] = is_detected
            self.confidences[roi_key] = confidence
            
            # If detected, mark as completed (for sequence)
            if is_detected:
                self.completed_targets.add(roi_key)
    
    def get_detected_holes(self) -> Set[str]:
        """Get all currently detected hole IDs."""
        return {k for k, v in self.roi_states.items() if v}
    
    def is_hole_detected(self, face: str, hole_id: str) -> bool:
        """Check if a specific hole is currently detected."""
        key = f"{face}_{hole_id}"
        return self.roi_states.get(key, False)
    
    def get_detection_age_ms(self, face: str, hole_id: str) -> Optional[float]:
        """Get how long ago detection started (in ms)."""
        key = f"{face}_{hole_id}"
        if key in self.detection_times:
            return (time.time() - self.detection_times[key]) * 1000
        return None


class LogicEngine:
    """
    Central rule evaluation engine with per-rule state machine.
    
    Each rule tracks its own lifecycle:
    - IDLE: waiting for input hole to be detected
    - MONITORING: input detected, waiting stable_window_s for outputs
    - DECIDED: PASS or FAIL emitted (stays here until input is removed)
    """
    
    def __init__(self, rules_file: str = "connectivity_rules.json",
                 stable_window_s: float = DEFAULT_STABLE_WINDOW_S):
        """
        Args:
            rules_file: Path to connectivity rules JSON
            stable_window_s: Seconds of sustained detection before deciding
        """
        self.rules: List[Dict] = []
        self.rules_by_input: Dict[str, List[Dict]] = {}  # "Face_HoleID" -> rules
        self.global_state = GlobalState()
        self.active_rule: Optional[str] = None
        self.evaluation_history: List[RuleEvaluationResult] = []
        self.stable_window_s = stable_window_s
        
        # System control state
        self._running = False
        self._paused = False
        
        # Manual overrides: rule_id -> "PASS" or "FAIL"
        self.manual_overrides: Dict[str, str] = {}
        
        # Per-rule state machine trackers
        self._rule_trackers: Dict[str, RuleTracker] = {}
        
        # Rule lookup helpers
        self.rule_input_key: Dict[str, str] = {}  # rule_id -> "Face_HoleID"
        self.rule_by_id: Dict[str, Dict] = {}  # rule_id -> rule dict
        
        # Guided sequence (legacy — kept for compatibility)
        self.target_sequence: List[str] = []  # List of unique "Face_HoleID"
        self.face_priority = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5}
        
        # ── Guided mode ──
        self.guided_mode: bool = False
        self._guided_sequence: List[Dict] = []   # built by build_guided_sequence()
        self._guided_step_index: int = 0          # current step index
        self._active_rule_id: Optional[str] = None  # rule being evaluated now
        
        # Debug throttle
        self._last_debug_print = 0.0
        
        # Load rules
        self.load_rules(rules_file)
    
    def load_rules(self, filepath: str) -> bool:
        """Load connectivity rules from JSON."""
        if not os.path.exists(filepath):
            print(f"[LogicEngine] Warning: Rules file not found: {filepath}")
            return False
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            self.rules = data.get('rules', [])
            
            # Index rules by input hole for fast lookup
            self.rules_by_input = {}
            self.rule_input_key = {}
            self.rule_by_id = {}
            self._rule_trackers = {}
            
            for rule in self.rules:
                input_face = rule.get('input', {}).get('face', '')
                input_hole = rule.get('input', {}).get('hole_id', '')
                key = f"{input_face}_{input_hole}"
                rid = rule.get('rule_id', '')
                if rid:
                    self.rule_input_key[rid] = key
                    self.rule_by_id[rid] = rule
                    # Create tracker for each rule
                    self._rule_trackers[rid] = RuleTracker(
                        rule_id=rid,
                        stable_window_s=self.stable_window_s
                    )
                if key not in self.rules_by_input:
                    self.rules_by_input[key] = []
                self.rules_by_input[key].append(rule)
            
            print(f"[LogicEngine] Loaded {len(self.rules)} rules, {len(self.rules_by_input)} unique inputs")
            print(f"[LogicEngine] Stable detection window: {self.stable_window_s}s")
            
            # Build target sequence
            unique_inputs = sorted(self.rules_by_input.keys(), 
                                 key=lambda k: (self.face_priority.get(k.split('_')[0], 99), k))
            self.target_sequence = unique_inputs
            print(f"[LogicEngine] Built target sequence: {len(self.target_sequence)} steps")
            
            return True
            
        except Exception as e:
            print(f"[LogicEngine] Error loading rules: {e}")
            return False
    
    def _check_outputs(self, rule: Dict, detected_holes: Set[str]) -> tuple:
        """
        Check which expected outputs are currently detected.
        
        Returns:
            (expected_keys, detected_keys, missing_keys)
        """
        expected_keys = []
        detected_keys = []
        missing_keys = []
        
        for output in rule.get('expected_outputs', []):
            out_face = output.get('face', '')
            out_hole = output.get('hole_id', '')
            out_key = f"{out_face}_{out_hole}"
            mandatory = output.get('mandatory', True)
            
            # Parse compound/alternative faces (e.g. "C_F" -> ["C","F"])
            candidate_faces = parse_face_to_faces(out_face)
            if not candidate_faces:
                expected_keys.append(out_key)
                if mandatory:
                    missing_keys.append(out_key)
                continue
            
            expected_keys.append(out_key)
            
            if len(candidate_faces) == 1:
                if self.global_state.is_hole_detected(out_face, out_hole):
                    detected_keys.append(out_key)
                elif mandatory:
                    missing_keys.append(out_key)
            else:
                # Compound/alternative: satisfied if ANY candidate face has hole detected
                if any(f"{f}_{out_hole}" in detected_holes for f in candidate_faces):
                    detected_keys.append(out_key)
                elif mandatory:
                    missing_keys.append(out_key)
        
        return expected_keys, detected_keys, missing_keys
    
    def _is_input_active(self, rule: Dict, detected_holes: Set[str]) -> bool:
        """Check if a rule's input is currently detected."""
        input_face = rule.get('input', {}).get('face', '')
        input_hole = rule.get('input', {}).get('hole_id', '')
        input_key = f"{input_face}_{input_hole}"
        return input_key in detected_holes
    
    def _all_outputs_detected(self, rule: Dict, detected_holes: Set[str]) -> bool:
        """True if all mandatory outputs are currently detected."""
        _, _, missing = self._check_outputs(rule, detected_holes)
        return len(missing) == 0
    
    def update_state(self, camera_result: Dict[str, Any]) -> List[RuleEvaluationResult]:
        """
        Process incoming detection result and evaluate rules using state machine.

        In GUIDED MODE: only the current active rule is evaluated. Only the
        expected output holes for that rule are checked — all other detections
        are ignored.

        In REACTIVE MODE (legacy): all rules are evaluated simultaneously.

        Args:
            camera_result: Detection result from camera worker

        Returns:
            List of rule evaluation results (0 or 1 per rule per activation)
        """
        # Always update camera state (keeps feeds live even when paused)
        self.global_state.update_from_detection(camera_result)

        # Debug: print detected holes every second
        now = time.time()
        if now - self._last_debug_print >= 1.0:
            detected_holes_debug = self.global_state.get_detected_holes()
            if detected_holes_debug:
                pass # print(f"[LogicEngine DEBUG] Detected holes: {sorted(detected_holes_debug)} | running={self._running} paused={self._paused} guided={self.guided_mode} active_rule={self._active_rule_id}")
            self._last_debug_print = now

        # Don't evaluate rules if stopped or paused
        if not self._running or self._paused:
            return []

        # ── GUIDED MODE: evaluate only the active rule ──
        if self.guided_mode:
            return self._update_state_guided(now)

        # ── REACTIVE MODE: evaluate all rules (legacy behaviour) ──
        return self._update_state_reactive(now)

    def _update_state_guided(self, now: float) -> List[RuleEvaluationResult]:
        """
        Guided mode evaluation: only check the current active rule.
        Only the expected output holes for that rule are considered;
        all other camera detections are ignored.
        """
        if not self._active_rule_id:
            return []

        rule = self.rule_by_id.get(self._active_rule_id)
        if not rule:
            return []

        tracker = self._rule_trackers.get(self._active_rule_id)
        if not tracker:
            return []

        # Build a FILTERED detected-holes set: only holes that are expected
        # outputs of the current rule (ignore everything else)
        current_step = self.get_current_guided_step()
        expected_output_keys: Set[str] = set()
        if current_step:
            for out in current_step['expected_outputs']:
                expected_output_keys.add(f"{out['face']}_{out['hole_id']}")

        all_detected = self.global_state.get_detected_holes()
        # Only keep detections that are expected outputs for this rule
        filtered_detected = {h for h in all_detected if h in expected_output_keys}

        results = []
        input_face = rule.get('input', {}).get('face', '')
        input_hole = rule.get('input', {}).get('hole_id', '')
        input_key = f"{input_face}_{input_hole}"

        # Check if the signal is valid (ONLY CHECKING EXPECTED OUTPUTS, IGNORING INPUT)
        # Reason: The operator's hand may obstruct the input hole during insertion.
        # Strict input checking would cause false negatives.
        
        # Check outputs using helper function
        expected_keys, detected_keys, missing_keys = self._check_outputs(
            rule, filtered_detected
        )
        
        logic = rule.get('logic', 'AND')
        if logic == 'AND':
            outputs_valid = (len(missing_keys) == 0 and len(detected_keys) == len(expected_keys))
        else:  # OR
            outputs_valid = len(detected_keys) > 0
            
        # Signal is valid if outputs are detected. Input state is ignored.
        signal_valid = outputs_valid

        if tracker.state == RuleState.IDLE:
            if signal_valid:
                # Start monitoring only when valid signal is detected
                tracker.start_monitoring()
                print(f"[LogicEngine GUIDED] ▶ {self._active_rule_id}: Signal OK -> MONITORING")

        elif tracker.state == RuleState.MONITORING:
            if signal_valid:
                tracker.touch()
                elapsed = now - tracker.monitoring_start
                
                # Check if stable duration met
                if elapsed >= tracker.stable_window_s:
                    decision = InspectionResult.PASS
                    tracker.decide(decision)

                    print(f"[LogicEngine GUIDED] ✓ {self._active_rule_id}: "
                          f"DECIDED ({decision.value}) after {elapsed:.1f}s | "
                          f"detected={detected_keys} missing={missing_keys}")

                    result = RuleEvaluationResult(
                        rule_id=self._active_rule_id,
                        result=decision,
                        input_hole=input_key,
                        expected_outputs=expected_keys,
                        detected_outputs=detected_keys,
                        missing_outputs=missing_keys,
                        evaluation_time_ms=round(elapsed * 1000, 1),
                        timestamp=datetime.now().isoformat()
                    )

                    self.evaluation_history.append(result)
                    if len(self.evaluation_history) > 1000:
                        self.evaluation_history = self.evaluation_history[-500:]

                    results.append(result)
            
            else:
                # Signal lost? Reset if grace period exceeded
                if tracker.input_lost_too_long(now):
                     print(f"[LogicEngine GUIDED] ◼ {self._active_rule_id}: Signal Lost -> IDLE")
                     tracker.reset()

        elif tracker.state == RuleState.DECIDED:
            # Stay decided until advance_guided_step() is called externally
            pass

        return results

    def _update_state_reactive(self, now: float) -> List[RuleEvaluationResult]:
        """
        Legacy reactive mode: evaluate all rules simultaneously.
        """
        results = []
        detected_holes = self.global_state.get_detected_holes()

        # ── Pass 1: Find output-matched rules ──
        output_matched_rules = set()
        suppressed_holes = set()

        for rule in self.rules:
            rule_id = rule.get('rule_id', '')
            if not rule_id:
                continue
            if self._all_outputs_detected(rule, detected_holes):
                output_matched_rules.add(rule_id)
                for output in rule.get('expected_outputs', []):
                    out_face = output.get('face', '')
                    out_hole = output.get('hole_id', '')
                    suppressed_holes.add(f"{out_face}_{out_hole}")

        # ── Pass 2: Evaluate each rule ──
        for rule in self.rules:
            rule_id = rule.get('rule_id', '')
            if not rule_id:
                continue

            tracker = self._rule_trackers.get(rule_id)
            if not tracker:
                continue

            is_output_matched = rule_id in output_matched_rules
            input_active_raw = self._is_input_active(rule, detected_holes)
            input_face = rule.get('input', {}).get('face', '')
            input_hole = rule.get('input', {}).get('hole_id', '')
            input_key = f"{input_face}_{input_hole}"
            input_suppressed = input_key in suppressed_holes
            input_active = input_active_raw and not input_suppressed
            triggered = is_output_matched or input_active

            if tracker.state == RuleState.IDLE:
                if triggered:
                    tracker.start_monitoring()
                    reason = "outputs matched" if is_output_matched else "input detected"
                    print(f"[LogicEngine] ▶ {rule_id}: IDLE → MONITORING ({reason})")

            elif tracker.state == RuleState.MONITORING:
                if not is_output_matched and input_suppressed:
                    tracker.reset()
                    continue

                if triggered:
                    tracker.touch()
                elif tracker.input_lost_too_long(now):
                    print(f"[LogicEngine] ◼ {rule_id}: MONITORING → IDLE "
                          f"(lost for >{tracker.grace_period_s}s at {tracker.elapsed_s():.1f}s)")
                    tracker.reset()
                    continue

                elapsed = now - tracker.monitoring_start
                if elapsed >= tracker.stable_window_s:
                    expected_keys, detected_keys, missing_keys = self._check_outputs(
                        rule, detected_holes
                    )
                    logic = rule.get('logic', 'AND')
                    if logic == 'AND':
                        passed = (len(missing_keys) == 0 and
                                  len(detected_keys) == len(expected_keys))
                    else:
                        passed = len(detected_keys) > 0

                    decision = InspectionResult.PASS if passed else InspectionResult.FAIL
                    tracker.decide(decision)

                    print(f"[LogicEngine] ✓ {rule_id}: MONITORING → DECIDED "
                          f"({decision.value}) after {elapsed:.1f}s | "
                          f"detected={detected_keys} missing={missing_keys}")

                    result = RuleEvaluationResult(
                        rule_id=rule_id,
                        result=decision,
                        input_hole=input_key,
                        expected_outputs=expected_keys,
                        detected_outputs=detected_keys,
                        missing_outputs=missing_keys,
                        evaluation_time_ms=round(elapsed * 1000, 1),
                        timestamp=datetime.now().isoformat()
                    )

                    self.evaluation_history.append(result)
                    if len(self.evaluation_history) > 1000:
                        self.evaluation_history = self.evaluation_history[-500:]

                    results.append(result)

            elif tracker.state == RuleState.DECIDED:
                if not triggered and tracker.input_lost_too_long(now):
                    tracker.reset()

        return results
    
    def get_monitoring_status(self) -> List[Dict[str, Any]]:
        """
        Get all rules currently in MONITORING state (for UI display).
        
        Returns:
            List of dicts with 'rule_id', 'elapsed_s', 'window_s', 'progress'
        """
        monitoring = []
        for rid, tracker in self._rule_trackers.items():
            if tracker.state == RuleState.MONITORING:
                elapsed = tracker.elapsed_s()
                monitoring.append({
                    'rule_id': rid,
                    'elapsed_s': round(elapsed, 1),
                    'window_s': tracker.stable_window_s,
                    'progress': min(1.0, elapsed / tracker.stable_window_s),
                })
        return monitoring
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get current system state summary."""
        detected = self.global_state.get_detected_holes()
        
        # Count tracker states
        idle_count = sum(1 for t in self._rule_trackers.values() if t.state == RuleState.IDLE)
        monitoring_count = sum(1 for t in self._rule_trackers.values() if t.state == RuleState.MONITORING)
        decided_count = sum(1 for t in self._rule_trackers.values() if t.state == RuleState.DECIDED)
        
        return {
            'detected_holes': list(detected),
            'detected_count': len(detected),
            'camera_health': self.global_state.camera_health,
            'rules_loaded': len(self.rules),
            'evaluations': len(self.evaluation_history),
            'trackers_idle': idle_count,
            'trackers_monitoring': monitoring_count,
            'trackers_decided': decided_count,
        }
    
    def get_last_evaluation(self) -> Optional[RuleEvaluationResult]:
        """Get most recent rule evaluation."""
        if self.evaluation_history:
            return self.evaluation_history[-1]
        return None
        
    def get_next_target(self) -> Optional[str]:
        """
        Get the next target hole ID in the sequence.
        Returns "Face_HoleID" or None if all complete.
        """
        for target in self.target_sequence:
            if target not in self.global_state.completed_targets:
                return target
        return None

    # ── Guided Mode ─────────────────────────────────────────

    def build_guided_sequence(self, available_faces: Optional[Set[str]] = None) -> List[Dict]:
        """
        Build an ordered inspection sequence for the guided mode.

        Filtering rules:
        - Exclude rules where ANY mandatory output has a single-face output
          that is NOT in available_faces (e.g. Face F when F is unavailable).
        - Compound faces like "C_F" are kept — they resolve to available faces.
        - Rules with Face F as INPUT are included (operator physically inserts laser).

        Ordering: input face A → B → C → D → E → F (F-input rules last).

        Args:
            available_faces: Set of face letters that have cameras (e.g. {'A','B','C','D','E'}).
                             Defaults to all 6 faces.

        Returns:
            List of step dicts:
            {
                'step_num': int,
                'rule_id': str,
                'input_face': str,
                'input_hole': str,
                'expected_outputs': [{'face': str, 'hole_id': str}],
            }
        """
        if available_faces is None:
            available_faces = set('ABCDEF')

        face_order = ['A', 'B', 'C', 'D', 'E', 'F']

        def _rule_has_unavailable_output(rule: Dict) -> bool:
            """True if rule has a mandatory output on a face with no camera."""
            for output in rule.get('expected_outputs', []):
                if not output.get('mandatory', True):
                    continue
                out_face = output.get('face', '')
                candidate_faces = parse_face_to_faces(out_face)
                if not candidate_faces:
                    continue
                # If ALL candidate faces are unavailable, this output can't be checked
                if all(f not in available_faces for f in candidate_faces):
                    return True
            return False

        # Collect eligible rules, deduplicated by rule_id
        seen_rule_ids: Set[str] = set()
        eligible: List[Dict] = []

        for rule in self.rules:
            rid = rule.get('rule_id', '')
            if not rid or rid in seen_rule_ids:
                continue
            if _rule_has_unavailable_output(rule):
                continue
            seen_rule_ids.add(rid)
            eligible.append(rule)

        # Sort by input face order, then by hole_id alphabetically
        def _sort_key(rule: Dict) -> tuple:
            face = rule.get('input', {}).get('face', 'Z')
            hole = rule.get('input', {}).get('hole_id', '')
            face_idx = face_order.index(face) if face in face_order else 99
            return (face_idx, hole)

        eligible.sort(key=_sort_key)

        # Build step list
        steps = []
        for i, rule in enumerate(eligible):
            input_face = rule.get('input', {}).get('face', '')
            input_hole = rule.get('input', {}).get('hole_id', '')

            # Build expected outputs — only those on available faces
            expected_outputs = []
            for output in rule.get('expected_outputs', []):
                out_face = output.get('face', '')
                out_hole = output.get('hole_id', '')
                candidate_faces = parse_face_to_faces(out_face)
                # Keep outputs that have at least one available candidate face
                available_candidates = [f for f in candidate_faces if f in available_faces]
                if available_candidates:
                    # Use first available candidate face for display
                    display_face = available_candidates[0]
                    expected_outputs.append({
                        'face': display_face,
                        'hole_id': out_hole,
                        'mandatory': output.get('mandatory', True),
                    })

            steps.append({
                'step_num': i + 1,
                'rule_id': rule.get('rule_id', ''),
                'input_face': input_face,
                'input_hole': input_hole,
                'expected_outputs': expected_outputs,
            })

        self._guided_sequence = steps
        print(f"[LogicEngine] Guided sequence built: {len(steps)} steps "
              f"(filtered from {len(self.rules)} total rules)")
        return steps

    def set_guided_step(self, step_index: int):
        """
        Activate a specific step in the guided sequence.
        Resets the tracker for the new active rule.

        Args:
            step_index: 0-based index into _guided_sequence
        """
        if not self._guided_sequence:
            return
        if step_index < 0 or step_index >= len(self._guided_sequence):
            return

        self._guided_step_index = step_index
        step = self._guided_sequence[step_index]
        new_rule_id = step['rule_id']

        # Reset previous active rule tracker
        if self._active_rule_id and self._active_rule_id != new_rule_id:
            old_tracker = self._rule_trackers.get(self._active_rule_id)
            if old_tracker:
                old_tracker.reset()

        self._active_rule_id = new_rule_id

        # Reset the new rule's tracker so it starts fresh
        tracker = self._rule_trackers.get(new_rule_id)
        if tracker:
            tracker.reset()

        print(f"[LogicEngine] Guided step set to {step_index + 1}/{len(self._guided_sequence)}: "
              f"{step['input_face']}_{step['input_hole']} → rule {new_rule_id}")

    def advance_guided_step(self) -> Optional[Dict]:
        """
        Move to the next step in the guided sequence.
        Returns the new step dict, or None if sequence is complete.
        """
        next_index = self._guided_step_index + 1
        if next_index >= len(self._guided_sequence):
            print("[LogicEngine] Guided sequence complete — all steps done.")
            return None
        self.set_guided_step(next_index)
        return self._guided_sequence[next_index]

    def get_current_guided_step(self) -> Optional[Dict]:
        """Return the current guided step dict, or None."""
        if not self._guided_sequence:
            return None
        if 0 <= self._guided_step_index < len(self._guided_sequence):
            return self._guided_sequence[self._guided_step_index]
        return None

    def get_guided_sequence(self) -> List[Dict]:
        """Return the full guided sequence."""
        return self._guided_sequence

    # ── System Control ──────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def start(self):
        """Start or restart the inspection cycle."""
        self._running = True
        self._paused = False
        self.global_state = GlobalState()  # Fresh state
        self.evaluation_history = []
        self.manual_overrides = {}
        # Reset all trackers
        for tracker in self._rule_trackers.values():
            tracker.reset()
        print("[LogicEngine] Inspection STARTED")

    def stop(self):
        """Stop the inspection cycle and reset all state."""
        self._running = False
        self._paused = False
        self.global_state = GlobalState()
        self.evaluation_history = []
        self.manual_overrides = {}
        for tracker in self._rule_trackers.values():
            tracker.reset()
        print("[LogicEngine] Inspection STOPPED")

    def pause(self):
        """Pause rule evaluation. Cameras keep running."""
        if self._running:
            self._paused = True
            print("[LogicEngine] Inspection PAUSED")

    def resume(self):
        """Resume rule evaluation."""
        if self._running:
            self._paused = False
            print("[LogicEngine] Inspection RESUMED")

    # ── Manual Overrides ────────────────────────────────────

    def add_override(self, rule_id: str, result: str) -> Optional[RuleEvaluationResult]:
        """
        Manually override a rule's result (PASS or FAIL).
        
        Args:
            rule_id: Rule ID to override
            result: "PASS" or "FAIL"
            
        Returns:
            RuleEvaluationResult representing the override, or None
        """
        if result not in ("PASS", "FAIL"):
            return None
        
        self.manual_overrides[rule_id] = result
        
        # Find the rule to get expected_outputs
        rule_dict = None
        for rule in self.rules:
            if rule.get('rule_id') == rule_id:
                rule_dict = rule
                break
        
        input_hole = ""
        expected_keys = []
        if rule_dict:
            input_face = rule_dict.get('input', {}).get('face', '')
            input_h = rule_dict.get('input', {}).get('hole_id', '')
            input_hole = f"{input_face}_{input_h}"
            for out in rule_dict.get('expected_outputs', []):
                expected_keys.append(f"{out.get('face', '')}_{out.get('hole_id', '')}")
        
        eval_result = RuleEvaluationResult(
            rule_id=rule_id,
            result=InspectionResult.PASS if result == "PASS" else InspectionResult.FAIL,
            input_hole=input_hole,
            expected_outputs=expected_keys,
            detected_outputs=expected_keys if result == "PASS" else [],
            missing_outputs=[] if result == "PASS" else expected_keys,
            evaluation_time_ms=0.0,
            timestamp=datetime.now().isoformat()
        )
        
        # Mark tracker as decided
        tracker = self._rule_trackers.get(rule_id)
        if tracker:
            tracker.decide(InspectionResult.PASS if result == "PASS" else InspectionResult.FAIL)
        
        self.evaluation_history.append(eval_result)
        print(f"[LogicEngine] Manual override: {rule_id} → {result}")
        return eval_result

    def clear_override(self, rule_id: str):
        """Remove a manual override."""
        self.manual_overrides.pop(rule_id, None)
        tracker = self._rule_trackers.get(rule_id)
        if tracker:
            tracker.reset()
        print(f"[LogicEngine] Override cleared: {rule_id}")

    def get_all_rule_ids(self) -> List[str]:
        """Get all rule IDs for the override dropdown."""
        return [r.get('rule_id', '') for r in self.rules]


# --- TESTING ---

if __name__ == "__main__":
    print("Logic Engine - Test")
    print("=" * 50)
    
    # Create engine with 2s window
    engine = LogicEngine("connectivity_rules.json", stable_window_s=2.0)
    
    # Print summary
    summary = engine.get_state_summary()
    print(f"\nState Summary:")
    print(f"  Rules loaded: {summary['rules_loaded']}")
    print(f"  Detected holes: {summary['detected_count']}")
    print(f"  Trackers: {summary['trackers_idle']} idle, "
          f"{summary['trackers_monitoring']} monitoring, "
          f"{summary['trackers_decided']} decided")
    
    # Simulate a detection
    print("\nSimulating detection from CAM_A...")
    mock_result = {
        'camera_id': 'CAM_A',
        'face': 'A',
        'detections': [
            {'hole_id': 'A1', 'laser': True, 'confidence': 0.95}
        ],
        'health': {'connected': True, 'fps': 120.0}
    }
    
    engine.start()
    evaluations = engine.update_state(mock_result)
    print(f"  Triggered {len(evaluations)} rule evaluations (should be 0 — monitoring)")
    
    monitoring = engine.get_monitoring_status()
    print(f"  Rules monitoring: {len(monitoring)}")
    for m in monitoring:
        print(f"    {m['rule_id']}: {m['elapsed_s']}s / {m['window_s']}s")

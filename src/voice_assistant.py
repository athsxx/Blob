"""
Offline Local Voice Assistant for Operator Guidance

Runs a dedicated daemon thread for Text-to-Speech (TTS) announcements so that
camera queues and the PyQt6 UI thread never block or lag.

Engine priority (100% offline):
1. Windows: PowerShell / SAPI.SpVoice (built into Windows 10/11, zero extra binary issues)
   or pyttsx3 if installed.
2. macOS: built-in `say` command (for local development/testing).
3. Fallback: silent no-op (never crashes or blocks inspection).
"""

from __future__ import annotations

import queue
import re
import subprocess
import sys
import threading
from typing import Dict, List, Optional

from logic_engine import parse_face_to_faces


def format_face_for_speech(face: str) -> str:
    """Convert raw face specifier (e.g. 'C_F', 'B_OR_D', 'A') into natural speech."""
    letters = parse_face_to_faces(str(face or ""))
    if not letters:
        return str(face or "")
    if len(letters) == 1:
        return f"Face {letters[0]}"
    return "Face " + " or ".join(letters)


def format_hole_for_speech(hole_id: str) -> str:
    """
    Convert technical hole IDs from the inspection sheet into clear spoken words.

    Examples:
        "A1" -> "A 1"
        "SEC. M-M" -> "Section M M"
        "SEC. T3-T3 COUNTER" -> "Section T 3 T 3 Counter"
        "Ø4 (OVAL HOLE) (SR. NO. 978)" -> "Diameter 4 Oval Hole, Serial Number 978"
        "Ø9.14 (SR. NO. 426 - A)" -> "Diameter 9.14, Serial Number 426 A"
        "STRIGHT HOLE (LE-LE)" -> "Straight Hole L E L E"
    """
    text = str(hole_id or "").strip()
    if not text:
        return "unknown hole"

    # Common domain replacements
    text = text.replace("Ø", "Diameter ").replace("ø", "Diameter ")
    text = re.sub(r"\bSEC\.?\s*", "Section ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSR\.?\s*NO\.?\s*", "Serial Number ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bSTRIGHT\b", "Straight", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCENTRE\b", "Center", text, flags=re.IGNORECASE)

    # Convert repeated section pairs like "M-M" or "T3-T3" or "JK-JK" into spaced tokens
    text = text.replace("(", ", ").replace(")", " ")
    text = text.replace("-", " ").replace("_", " ")

    # Space out single letter + number codes like A1 -> A 1, B15 -> B 15 for clearer TTS
    text = re.sub(r"\b([A-Za-z])(\d+)\b", r"\1 \2", text)

    # Clean up excess whitespace and punctuation
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    return text


def build_step_prompt_speech(step: Dict, total_steps: int = 0) -> str:
    """Build the spoken instruction when a new step/insert timer starts."""
    step_num = step.get("step_num", 1)
    face_spoken = format_face_for_speech(step.get("input_face", ""))
    hole_spoken = format_hole_for_speech(step.get("input_hole", ""))
    is_manual = str(step.get("execution") or "auto").strip().lower() == "manual"

    if is_manual:
        return (
            f"Rule {step_num}, manual check. "
            f"Please insert the laser in {face_spoken}, hole {hole_spoken}, "
            f"and select Pass or Fail."
        )
    return (
        f"Rule {step_num}. "
        f"Please insert the laser in {face_spoken}, hole {hole_spoken}."
    )


def build_step_result_speech(
    step_num: int,
    passed: bool,
    has_next_step: bool = True,
    timed_out: bool = False,
) -> str:
    """Build the spoken announcement when a rule passes or fails."""
    if passed:
        if has_next_step:
            return f"Rule {step_num} Passed. Please move to the next hole insert."
        return f"Rule {step_num} Passed."
    else:
        reason = "timed out and Failed" if timed_out else "Failed"
        if has_next_step:
            return f"Rule {step_num} {reason}. Please move to the next hole insert."
        return f"Rule {step_num} {reason}."


def build_completion_speech(passed_count: int, failed_count: int) -> str:
    """Build the spoken summary when all steps in the sequence complete."""
    total = passed_count + failed_count
    if failed_count == 0 and total > 0:
        return f"Inspection complete. All {total} rules passed."
    return (
        f"Inspection complete. {passed_count} passed, {failed_count} failed. "
        f"Please review failed rules."
    )


class VoiceAssistant:
    """
    Non-blocking offline voice announcer using a dedicated background daemon thread.

    Supports immediate pre-emption (`interrupt=True`) so rapid step transitions
    never queue up stale audio behind the live UI state.
    """

    def __init__(self, enabled: bool = True, rate: int = 1):
        self._enabled = bool(enabled)
        self._rate = int(rate)  # SAPI rate (-10 to 10; 1 is slightly brisk & clear)
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._stop_event = threading.Event()
        self._current_proc: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run_loop,
            name="VoiceAssistantWorker",
            daemon=True,
        )
        self._worker.start()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.clear_pending()

    def toggle(self) -> bool:
        """Toggle voice mute/unmute state and return new enabled state."""
        self.set_enabled(not self._enabled)
        return self._enabled

    def clear_pending(self) -> None:
        """Drain queued utterances and terminate any active subprocess speech."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._proc_lock:
            if self._current_proc is not None:
                try:
                    self._current_proc.terminate()
                except Exception:
                    pass
                self._current_proc = None

    def speak(self, text: str, interrupt: bool = False) -> None:
        """
        Queue a spoken message without blocking the caller.

        Args:
            text: Sentence to speak.
            interrupt: If True, clears any pending queued messages first.
        """
        if not self._enabled or not text or not str(text).strip():
            return
        if interrupt:
            self.clear_pending()
        self._queue.put(str(text).strip())

    def announce_step_start(self, step: Dict, total_steps: int = 0) -> None:
        """Announce the hole where the operator should insert the laser."""
        if not step:
            return
        msg = build_step_prompt_speech(step, total_steps)
        # Do not interrupt an in-flight PASS/FAIL utterance; queue right behind it
        self.speak(msg, interrupt=False)

    def announce_step_result(
        self,
        step_num: int,
        passed: bool,
        has_next_step: bool = True,
        timed_out: bool = False,
    ) -> None:
        """Announce PASS/FAIL for the current rule."""
        msg = build_step_result_speech(
            step_num=step_num,
            passed=passed,
            has_next_step=has_next_step,
            timed_out=timed_out,
        )
        # Interrupt any stale "please insert..." prompt from the step that just finished
        self.speak(msg, interrupt=True)

    def announce_completion(self, passed_count: int, failed_count: int) -> None:
        """Announce final inspection disposition."""
        msg = build_completion_speech(passed_count, failed_count)
        self.speak(msg, interrupt=False)

    def shutdown(self) -> None:
        """Cleanly stop the background voice thread."""
        self._stop_event.set()
        self.clear_pending()
        self._queue.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=1.5)

    # ── Internal Worker Loop ──────────────────────────────────

    def _run_loop(self) -> None:
        """Single background thread that serializes all TTS playback."""
        # Try initializing pyttsx3 or win32com SAPI in this thread on Windows
        sapi_voice = None
        pyttsx_engine = None

        if sys.platform == "win32":
            try:
                import pythoncom  # type: ignore
                import win32com.client  # type: ignore

                pythoncom.CoInitialize()
                sapi_voice = win32com.client.Dispatch("SAPI.SpVoice")
                sapi_voice.Rate = self._rate
                sapi_voice.Volume = 100
            except Exception:
                sapi_voice = None
                try:
                    import pyttsx3  # type: ignore

                    pyttsx_engine = pyttsx3.init()
                    pyttsx_engine.setProperty("rate", 175)
                    pyttsx_engine.setProperty("volume", 1.0)
                except Exception:
                    pyttsx_engine = None

        while not self._stop_event.is_set():
            try:
                utterance = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if utterance is None or self._stop_event.is_set():
                break
            if not self._enabled:
                continue

            self._speak_blocking(utterance, sapi_voice, pyttsx_engine)

        if sys.platform == "win32" and sapi_voice is not None:
            try:
                import pythoncom  # type: ignore

                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _speak_blocking(self, text: str, sapi_voice, pyttsx_engine) -> None:
        """Execute TTS inside the worker thread."""
        try:
            if sys.platform == "win32":
                if sapi_voice is not None:
                    sapi_voice.Speak(text)
                    return
                if pyttsx_engine is not None:
                    pyttsx_engine.say(text)
                    pyttsx_engine.runAndWait()
                    return
                # Built-in Windows PowerShell System.Speech fallback (zero pip packages needed)
                safe_text = text.replace("'", " ").replace('"', " ")
                ps_script = (
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    f"$s.Rate = {self._rate}; "
                    f"$s.Speak('{safe_text}');"
                )
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                with self._proc_lock:
                    self._current_proc = subprocess.Popen(
                        [
                            "powershell",
                            "-NoProfile",
                            "-NonInteractive",
                            "-Command",
                            ps_script,
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creationflags,
                    )
                self._current_proc.wait(timeout=15)
                with self._proc_lock:
                    self._current_proc = None
                return

            if sys.platform == "darwin":
                with self._proc_lock:
                    self._current_proc = subprocess.Popen(
                        ["say", "-r", "190", text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                self._current_proc.wait(timeout=15)
                with self._proc_lock:
                    self._current_proc = None
                return
        except Exception:
            with self._proc_lock:
                self._current_proc = None

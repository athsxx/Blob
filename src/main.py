"""
Multi-Camera Manifold Inspection System — Main Entry Point

Launches camera workers, initializes the dashboard, and runs the
central inspection loop.

Usage:
    python main.py              # Run with all cameras (PyQt6 UI)
    python main.py --cv         # Force OpenCV fallback dashboard
    python main.py --no-display # Run headless (no preview windows)
"""

import multiprocessing as mp
import time
import queue
import os
import sys
import argparse
from datetime import datetime
from typing import Optional

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# macOS only: hint Qt where platform plugins live (no-op on Windows/Linux)
if sys.platform == "darwin":
    try:
        import PyQt6
        _p = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "plugins", "platforms")
        if os.path.isdir(_p):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", _p)
    except ImportError:
        pass

import cv2

from config_loader import (
    load_cameras,
    manifold_data_subdirectory,
    manifold_folder_for_label,
    validate_enabled_cameras,
    connectivity_rules_path_ok,
)
from camera_worker import camera_worker_process
from camera_indexer import resolve_camera_indices, check_port_map_exists
from dashboard import create_dashboard, HAS_PYQT6
from logic_engine import LogicEngine
from logger import get_logger


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Multi-Camera Manifold Inspection')
    parser.add_argument('--no-display', action='store_true', help='Run without preview')
    parser.add_argument('--cv', action='store_true', help='Force OpenCV dashboard (no PyQt6)')
    parser.add_argument(
        '--skip-indexing', action='store_true',
        help=(
            'Skip USB port-path camera index resolution and use cameras.json usb_index as-is. '
            'Use ONLY for development/testing. In production always run the assignment wizard first.'
        )
    )
    # Resolve config dir relative to project root (parent of src/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_config_dir = os.path.join(project_root, 'config')
    parser.add_argument('--config-dir', default=default_config_dir, help='Config directory path')
    args = parser.parse_args()
    args.config_dir = os.path.abspath(os.path.expanduser(args.config_dir))

    if not os.path.isdir(args.config_dir):
        print(f"[ERROR] Config directory does not exist or is not a folder:\n  {args.config_dir}")
        return

    # Initialize Logger (always under project root, not CWD)
    logger = get_logger(os.path.join(project_root, "logs"))
    logger.log_system("INFO", "System starting up...")

    print("=" * 60)
    print("MULTI-CAMERA MANIFOLD INSPECTION SYSTEM")
    print("=" * 60)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Load configuration
    cameras_file = os.path.join(args.config_dir, 'cameras.json')
    cameras = load_cameras(cameras_file)

    if not cameras:
        msg = "[ERROR] No cameras configured. Check config/cameras.json"
        print(msg)
        logger.log_system("ERROR", msg)
        logger.stop()
        return

    cam_errors = validate_enabled_cameras(cameras)
    if cam_errors:
        for e in cam_errors:
            print(f"[ERROR] {e}")
            logger.log_system("ERROR", e)
        logger.stop()
        return

    # Defer Logic Engine initialization until manifold is selected

    # ── Multiprocessing setup ──
    ctx = mp.get_context('spawn')
    result_queue = ctx.Queue()
    display_queue = ctx.Queue(maxsize=18) if not args.no_display else None
    control_event = ctx.Event()
    ready_queue = ctx.Queue()

    processes = []

    # ── Dashboard setup ──
    dashboard = None
    qt_app = None

    if not args.no_display:
        force_cv = args.cv
        dashboard, qt_app = create_dashboard(
            total_rules=0,
            force_cv=force_cv,
            cameras=cameras,
            config_dir=os.path.abspath(args.config_dir),
            project_root=project_root,
            cameras_file=os.path.abspath(cameras_file),
        )
        ui_mode = "PyQt6" if qt_app else "OpenCV"
        print(f"[Main] Dashboard initialized ({ui_mode}).")

    # ── Deterministic Camera Index Resolution (Windows: USB port-path fingerprinting) ──
    # Port map is written by the in-app Assign faces wizard or tools/assign_camera_faces.py.
    if args.skip_indexing:
        print("[Main] --skip-indexing flag set: using cameras.json usb_index values as-is.")
        print("       WARNING: camera-face mapping may be incorrect after a reboot or USB change.")
        logger.log_system("WARN", "--skip-indexing: USB port-path resolution bypassed")
    else:
        if sys.platform == "win32" and not check_port_map_exists(args.config_dir):
            print("[Main] camera_port_map.json missing — face assignment required.")
            assigned = False
            if qt_app and dashboard and hasattr(dashboard, "run_face_assign_wizard"):
                assigned = bool(dashboard.run_face_assign_wizard(required=True))
            if not assigned:
                msg = (
                    "camera_port_map.json is missing. Assign cameras in the app "
                    "(Assign camera faces) or run: python tools/assign_camera_faces.py"
                )
                print(f"[ERROR] {msg}")
                logger.log_system("ERROR", msg)
                logger.stop()
                return
            cameras = load_cameras(cameras_file)
            cam_errors = validate_enabled_cameras(cameras)
            if cam_errors:
                for e in cam_errors:
                    print(f"[ERROR] {e}")
                logger.stop()
                return
        try:
            cameras = resolve_camera_indices(cameras, args.config_dir)
        except RuntimeError as e:
            print(str(e))
            logger.log_system("ERROR", str(e))
            logger.stop()
            return
        except Exception as e:
            msg = f"Camera index resolver error: {e}. Falling back to cameras.json indices."
            print(f"[WARN] {msg}")
            logger.log_system("WARN", msg)

    inspection_mode = "sequential"  # default
    selected_manifold = "DALIA"     # default
    
    # Wait for mode and manifold selection from integrated Start Pages
    if qt_app:
        print("[Main] Waiting for operator to select Mode and Manifold...")
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        dashboard.set_setup_event_loop(loop)

        def on_manifold_selected(manifold):
            dashboard.selected_manifold = manifold
            loop.quit()  # Break out of the event loop after both are selected

        dashboard.sig_manifold_selected.connect(on_manifold_selected)
        loop.exec()  # Run full Qt event loop to ensure UI is responsive
        dashboard.set_setup_event_loop(None)

        inspection_mode = getattr(dashboard, 'selected_mode', None)
        selected_manifold = getattr(dashboard, 'selected_manifold', None)

        if not inspection_mode or not selected_manifold:
            print("[Main] Operator closed window before completing setup. Exiting.")
            logger.log_system("INFO", "Setup aborted (window closed or incomplete selection)")
            logger.stop()
            return

    # ── Dynamic Configuration Loading ──
    print(f"\n[Main] Operator Selected: Mode={inspection_mode}, Manifold={selected_manifold}")

    # Reload + re-resolve after setup (operator may have assigned faces on the prep page)
    cameras = load_cameras(cameras_file)
    if not args.skip_indexing:
        try:
            cameras = resolve_camera_indices(cameras, args.config_dir)
        except Exception as e:
            print(f"[WARN] Camera index resolver error after setup: {e}")
            logger.log_system("WARN", str(e))
    if dashboard and hasattr(dashboard, "apply_resolved_cameras"):
        dashboard.apply_resolved_cameras(cameras)
    
    # Rules + ROI folder from manifolds_registry.json (label → config subfolder)
    cfg_folder = manifold_folder_for_label(selected_manifold, args.config_dir) or "DALIA"
    rule_file = os.path.normpath(
        os.path.join(args.config_dir, cfg_folder, "connectivity_rules.json")
    )

    ok_rules, rules_path_report = connectivity_rules_path_ok(args.config_dir, cfg_folder)
    if not ok_rules:
        msg = (
            f"Invalid or missing connectivity rules for manifold {selected_manifold!r} "
            f"(folder {cfg_folder!r}).\nExpected a non-empty 'rules' array in:\n  {rules_path_report}"
        )
        print(f"[ERROR] {msg}")
        logger.log_system("ERROR", msg)
        if qt_app and dashboard:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(
                dashboard,
                "Configuration error",
                msg,
            )
        logger.stop()
        return

    # Initialize Logic Engine dynamically
    engine = LogicEngine(rule_file)
    total_rules = len(engine.rules)
    if total_rules == 0:
        msg = f"Rules file loaded but contains 0 rules:\n  {rule_file}"
        print(f"[ERROR] {msg}")
        logger.log_system("ERROR", msg)
        if qt_app and dashboard:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(dashboard, "Configuration error", msg)
        logger.stop()
        return

    print(f"[Main] Logic Engine initialized with {total_rules} rules for {selected_manifold}.")
    logger.log_system("INFO", f"Logic Engine initialized with {total_rules} rules for {selected_manifold}")
    
    # Resolve ROI JSON folder (Manifold 2/3 share DALIA on disk until separate trees exist)
    roi_subdir = manifold_data_subdirectory(selected_manifold, args.config_dir)
    print("\nCamera → Face Mapping:")
    for cam in cameras:
        status = "✓" if cam.get('enabled', True) else "✗"
        if selected_manifold:
            cam['config'] = f"config/{roi_subdir}/{os.path.basename(cam['config'])}"
        print(f"  [{status}] USB {cam['usb_index']} → Face {cam['face']} → {cam['config']}")
        cfg_rel = cam["config"]
        abs_roi = (
            cfg_rel
            if os.path.isabs(cfg_rel)
            else os.path.abspath(os.path.join(os.path.dirname(cameras_file), "..", cfg_rel))
        )
        if not os.path.isfile(abs_roi):
            w = f"ROI file missing for Face {cam['face']}: {abs_roi}"
            print(f"  [WARN] {w}")
            logger.log_system("WARN", w)
    print()

    # Pass the total rules to dashboard now that we know them
    if dashboard:
        dashboard.progress_bar.setRange(0, total_rules)
        dashboard.progress_bar.setFormat(f"%v / {total_rules} steps")

    # ── Build guided sequence (Sequential or manual/custom single rule) ──
    guided_sequence = []
    available_faces = {
        str(c.get("face", "")).upper()
        for c in cameras
        if c.get("enabled", True) and c.get("face")
    }
    if not available_faces:
        available_faces = {"A", "B", "C", "D", "E", "F"}
    custom_rule_id = getattr(dashboard, "custom_rule_id", None) if dashboard else None

    if inspection_mode == "sequential":
        guided_sequence = engine.build_guided_sequence(available_faces)
        engine.guided_mode = True
        if guided_sequence:
            engine.set_guided_step(0)
        print(
            f"[Main] Guided sequence: {len(guided_sequence)} steps "
            f"(faces {', '.join(sorted(available_faces))})"
        )
        if not guided_sequence and total_rules > 0:
            w = (
                "Sequential mode: no guided steps after filtering (check cameras vs rule outputs). "
                "Inspection START will not advance steps — use manual/reactive flow or fix rules."
            )
            print(f"[WARN] {w}")
            logger.log_system("WARN", w)

    elif inspection_mode == "custom":
        if custom_rule_id:
            step = engine.build_single_guided_step(custom_rule_id, available_faces, step_num=1)
            if step:
                guided_sequence = [step]
                engine.guided_mode = True
                engine._guided_sequence = guided_sequence
                engine.set_guided_step(0)
                print(f"[Main] Manual mode: single rule {custom_rule_id}")
            else:
                engine.guided_mode = False
                print(f"[Main] Manual rule {custom_rule_id!r} not runnable with current cameras — reactive mode")
        else:
            engine.guided_mode = False
            print("[Main] Manual mode: no rule selected — reactive mode (all rules)")

    if dashboard and guided_sequence and hasattr(dashboard, 'load_guided_sequence'):
        dashboard.load_guided_sequence(guided_sequence)


    # ── Start camera workers ──
    print()
    print("Starting camera workers...")
    logger.log_system("INFO", "Starting camera workers")

    # Serialize camera opens to reduce USB contention
    global_open_semaphore = ctx.Semaphore(1)

    # Communication queues for sending commands to workers
    comm_queues = {} # Face -> Queue

    # Open cameras sequentially by USB index
    cameras_sorted = sorted(cameras, key=lambda c: c.get('usb_index', 0))

    for cam in cameras_sorted:
        if not cam.get('enabled', True):
            continue

        config_path = cam['config']
        if not os.path.isabs(config_path):
            # Resolve relative to config dir, then make absolute so worker finds file regardless of cwd
            config_path = os.path.join(os.path.dirname(cameras_file), '..', config_path)
            config_path = os.path.abspath(config_path)

        presets = [
            {
                "width": cam.get("width", 640),
                "height": cam.get("height", 480),
                "fps": cam.get("fps", 15),
                # MJPG first on Windows so five OV5693 cams fit on an extended hub.
                **({"fourcc": "MJPG"} if sys.platform == "win32" else {}),
            },
            {
                # Fallback: native/YUY2 at the same (ROI-calibrated) resolution.
                # Do not fall back to 320x240 — ROI coordinates are in 640x480 space.
                "width": cam.get("width", 640),
                "height": cam.get("height", 480),
                "fps": cam.get("fps", 15),
            },
        ]

        backend = "dshow"
        if sys.platform != "win32":
            backend = "auto"

        capture_settings = {
            "backend": backend,
            # Do not fall through to MSMF: its index order can differ from DSHOW / the port map.
            "allow_backend_fallback": False,
            "presets": presets,
            "warmup_reads": 8 if sys.platform == "win32" else 5,
            "open_settle_s": 1.5 if sys.platform == "win32" else 1.0,
            "robust_mode": True,
            "max_read_retries": 10,
            "max_reconnect_attempts": 8,
            "min_width": int(cam.get("width", 640)),
            "target_fps": 15,
            "reject_high_res": False,
            "reject_high_fps": False,
        }
        if cam.get("device_path"):
            capture_settings["device_path"] = cam["device_path"]

        hub_id = cam.get("hub", 0)
        open_semaphore = global_open_semaphore

        if qt_app:
            qt_app.processEvents()

        c_queue = ctx.Queue()
        comm_queues[cam['face']] = c_queue

        p = ctx.Process(
            target=camera_worker_process,
            args=(
                cam['usb_index'],
                cam['face'],
                config_path,
                result_queue,
                control_event,
                display_queue,
                capture_settings,
                hub_id,
                open_semaphore,
                c_queue,
                ready_queue,
            )
        )
        p.start()
        processes.append(p)
        msg = f"Started worker for Face {cam['face']} (USB {cam['usb_index']}, hub {hub_id})"
        print(f"  {msg}")
        logger.log_system("INFO", msg)

        # Handshake: wait for first connect result before opening the next camera.
        ready_timeout_s = 25.0
        deadline = time.time() + ready_timeout_s
        got_ready = False
        while time.time() < deadline:
            if qt_app:
                qt_app.processEvents()
            try:
                report = ready_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if str(report.get("face", "")).upper() != str(cam["face"]).upper():
                continue
            got_ready = True
            if report.get("ok"):
                print(
                    f"  [OK] Face {cam['face']} opened "
                    f"{report.get('width')}x{report.get('height')} "
                    f"(backend={report.get('backend')})"
                )
            else:
                print(f"  [FAIL] Face {cam['face']} did not open — continuing with remaining cameras")
                logger.log_system("WARN", f"Face {cam['face']} initial open failed")
            break
        if not got_ready:
            print(f"  [WARN] Face {cam['face']} did not report ready within {ready_timeout_s:.0f}s")

    print()
    print("=" * 60)
    print("SYSTEM RUNNING — Press 'q' in Dashboard or Ctrl+C to stop")
    print("=" * 60)
    print()

    # ── Main Loop ──
    # PyQt6: use QTimer-driven polling
    # OpenCV: use traditional while-loop

    if qt_app and dashboard:
        # PyQt6 mode — poll queues via timer
        try:
            from PyQt6.QtCore import QTimer

            # Throttle UI log: at most one dashboard update per rule per second (structured, not per-frame)
            log_ui_throttle = {}  # rule_id -> last time we sent this rule to dashboard
            LOG_UI_INTERVAL_SEC = 1.0

            # Connect dashboard control signals to logic engine
            # Connect dashboard control signals to logic engine
            
            # ── Per-step timeout (60 seconds) ──
            STEP_TIMEOUT_SECS = 60
            step_timeout_remaining = [0]   # mutable container for closure
            step_timed_out = [False]        # guard against double-advance

            def _reset_step_timer():
                step_timeout_remaining[0] = STEP_TIMEOUT_SECS
                step_timed_out[0] = False
                if hasattr(dashboard, 'instruction_panel'):
                    dashboard.instruction_panel.set_countdown(STEP_TIMEOUT_SECS)

            def _tick_step_timer():
                """Called every 1 second while inspection is running."""
                if not engine._running or engine._paused:
                    return
                if step_timed_out[0]:
                    return
                step_timeout_remaining[0] -= 1
                remaining = step_timeout_remaining[0]
                if hasattr(dashboard, 'instruction_panel'):
                    dashboard.instruction_panel.set_countdown(remaining)
                if remaining <= 0:
                    # Auto-fail this step
                    step_timed_out[0] = True
                    step_idx = engine._guided_step_index
                    rule_id = engine._active_rule_id
                    print(f"[Main] Step {step_idx + 1} TIMED OUT — auto-fail")
                    logger.log_system("INFO", f"Step {step_idx + 1} timed out (60s)")

                    # Use override mechanism to record a formal FAIL result
                    if rule_id:
                        eval_result = engine.add_override(rule_id, "FAIL")
                        if eval_result:
                            logger.log_inspection(eval_result.to_dict())
                            dashboard.update_result(eval_result.to_dict())
                    else:
                        logger.log_system("WARN", "Step timeout but no active rule id — skip override")

                    if engine._guided_sequence and 0 <= step_idx < len(engine._guided_sequence):
                        dashboard.update_step_result(step_idx, passed=False)
                    # Advance after 2 seconds
                    def _advance_after_timeout():
                        next_step = engine.advance_guided_step()
                        if next_step is not None:
                            new_idx = engine._guided_step_index
                            dashboard.update_guided_step(new_idx)
                            _reset_step_timer()
                        else:
                            dashboard.instruction_panel.status_lbl.setText("✓  ALL STEPS COMPLETE")
                            dashboard.instruction_panel.status_lbl.setStyleSheet(
                                "color: #3fb950; font-size: 24px; font-weight: bold;"
                            )
                            dashboard.instruction_panel.countdown_lbl.setText("")
                    QTimer.singleShot(2000, _advance_after_timeout)

            step_timer = QTimer()
            step_timer.timeout.connect(_tick_step_timer)
            step_timer.setInterval(1000)  # 1 second

            # Control handlers with timer integration
            def _on_start():
                engine.start()
                log_ui_throttle.clear()
                logger.log_system("INFO", "Inspection STARTED by operator")
                _reset_step_timer()
                step_timer.start()

            def _on_stop():
                engine.stop()
                step_timer.stop()
                logger.log_system("INFO", "Inspection STOPPED by operator")

            def _on_pause():
                engine.pause()
                step_timer.stop()
                logger.log_system("INFO", "Inspection PAUSED by operator")

            def _on_resume():
                engine.resume()
                step_timer.start()
                logger.log_system("INFO", "Inspection RESUMED by operator")

            dashboard.sig_start.connect(_on_start)
            dashboard.sig_stop.connect(_on_stop)
            dashboard.sig_pause.connect(_on_pause)
            dashboard.sig_resume.connect(_on_resume)

            # Manual override handler
            def handle_override(rule_id: str, result: str):
                eval_result = engine.add_override(rule_id, result)
                if eval_result:
                    logger.log_inspection(eval_result.to_dict())
                    dashboard.update_result(eval_result.to_dict())
                    print(f"[Main] Manual override: {rule_id} → {result}")
                    logger.log_system("INFO", f"Manual override: {rule_id} → {result}")

            dashboard.sig_override.connect(handle_override)

            # Populate rule IDs for override dialog
            dashboard.set_rule_ids(engine.get_all_rule_ids())

            def poll_queues():
                """Called ~60 times/sec by QTimer."""
                # 1. Drain display queue to latest frame per camera (zero lag, no queue buildup)
                if display_queue:
                    latest_frames = {}
                    drained = 0
                    while drained < 30:  # Drain pending burst up to 30 frames
                        try:
                            camera_id, frame = display_queue.get_nowait()
                            latest_frames[camera_id] = frame
                            drained += 1
                        except queue.Empty:
                            break

                    for camera_id, frame in latest_frames.items():
                        dashboard.update_frame(camera_id, frame)

                # 2. Drain result queue
                try:
                    result_drained = 0
                    while result_drained < 10: # Strict cap for logic engine
                        result = result_queue.get_nowait()
                        result_drained += 1
                        try:
                            evaluations = engine.update_state(result)
                        except Exception as ex:
                            logger.log_system("ERROR", f"update_state failed: {ex}")
                            evaluations = []

                        # Update camera health in dashboard
                        cid = result.get('camera_id', '')
                        fps = result.get('health', {}).get('fps', 0)
                        dets = sum(1 for d in result.get('detections', []) if d.get('laser'))
                        dashboard.update_health(cid, fps, dets)
                        # Show live detected holes so operator can see if pipeline has detections
                        detected = list(engine.get_state_summary().get('detected_holes', []))
                        dashboard.update_detected_state(detected)

                        # Show monitoring status (rules counting up to 2s window)
                        monitoring = engine.get_monitoring_status()
                        dashboard.update_monitoring(monitoring)

                        for eval_result in evaluations:
                            logger.log_inspection(eval_result.to_dict())
                            # UI: show every PASS/FAIL (now one-shot per activation)
                            dashboard.update_result(eval_result.to_dict())
                            # Terminal: print result
                            rid = eval_result.rule_id
                            now_t = time.time()
                            if now_t - log_ui_throttle.get(rid, 0) >= LOG_UI_INTERVAL_SEC:
                                log_ui_throttle[rid] = now_t
                                res_str = eval_result.result.value
                                if res_str == "PASS":
                                    print(f"[Inspection]  {res_str}  {rid}")
                                else:
                                    miss = eval_result.missing_outputs
                                    print(f"[Inspection]  {res_str}  {rid}" + (f"  (missing: {miss})" if miss else ""))

                            # ── Guided mode: update step result and advance ──
                            if engine.guided_mode and hasattr(dashboard, 'update_step_result'):
                                step_idx = engine._guided_step_index
                                passed = (eval_result.result.value == "PASS")
                                dashboard.update_step_result(step_idx, passed)

                                # Only advance if timeout hasn't already fired for this step
                                if not step_timed_out[0]:
                                    step_timed_out[0] = True  # prevent timeout from also advancing

                                    # Advance to next step after a short delay
                                    def _advance_step(idx=step_idx):
                                        next_step = engine.advance_guided_step()
                                        if next_step is not None:
                                            new_idx = engine._guided_step_index
                                            dashboard.update_guided_step(new_idx)
                                            _reset_step_timer()
                                        else:
                                            # Sequence complete
                                            dashboard.instruction_panel.status_lbl.setText(
                                                "✓  ALL STEPS COMPLETE"
                                            )
                                            dashboard.instruction_panel.status_lbl.setStyleSheet(
                                                "color: #3fb950; font-size: 24px; font-weight: bold;"
                                            )
                                            dashboard.instruction_panel.countdown_lbl.setText("")

                                    from PyQt6.QtCore import QTimer as _QTimer
                                    _QTimer.singleShot(2000, _advance_step)


                except queue.Empty:
                    pass

                # Update monitoring progress in instruction panel
                if engine.guided_mode and hasattr(dashboard, 'update_monitoring_progress'):
                    monitoring = engine.get_monitoring_status()
                    if monitoring:
                        m = monitoring[0]
                        pct = int(m.get('progress', 0) * 100)
                        dashboard.update_monitoring_progress(pct)
                    else:
                        # Check if we're in MONITORING state (guided mode auto-starts)
                        current_step = engine.get_current_guided_step()
                        if current_step:
                            active_rule_id = engine._active_rule_id
                            tracker = engine._rule_trackers.get(active_rule_id)
                            if tracker:
                                from logic_engine import RuleState
                                if tracker.state == RuleState.MONITORING:
                                    elapsed = time.time() - tracker.monitoring_start
                                    pct = min(100, int((elapsed / tracker.stable_window_s) * 100))
                                    dashboard.update_monitoring_progress(pct)

                # Check if any workers died
                alive = [p for p in processes if p.is_alive()]
                if len(alive) == 0 and not control_event.is_set():
                    print("[Main] All workers stopped unexpectedly.")

            timer = QTimer()
            timer.timeout.connect(poll_queues)
            timer.start(16)  # ~60fps UI refresh

            dashboard.showMaximized()
            dashboard.raise_()
            dashboard.activateWindow()
            qt_app.exec()

        except KeyboardInterrupt:
            print("\n[Main] Shutdown requested...")
            logger.log_system("INFO", "Shutdown requested via KeyboardInterrupt")

    else:
        # OpenCV fallback / headless mode
        log_ui_throttle = {}
        LOG_UI_INTERVAL_SEC = 1.0
        try:
            while True:
                if dashboard and display_queue:
                    latest_frames = {}
                    try:
                        while True:
                            camera_id, frame = display_queue.get_nowait()
                            latest_frames[camera_id] = frame
                    except queue.Empty:
                        pass

                    for camera_id, frame in latest_frames.items():
                        dashboard.update_frame(camera_id, frame)

                    key = dashboard.show()
                    if key == ord('q'):
                        print("\n[Main] Quit requested.")
                        logger.log_system("INFO", "User requested quit")
                        break

                try:
                    while True:
                        result = result_queue.get_nowait()
                        try:
                            evaluations = engine.update_state(result)
                        except Exception as ex:
                            logger.log_system("ERROR", f"update_state failed: {ex}")
                            evaluations = []
                        for eval_result in evaluations:
                            logger.log_inspection(eval_result.to_dict())
                            if dashboard:
                                dashboard.update_result(eval_result.to_dict())
                            rid = eval_result.rule_id
                            now = time.time()
                            if now - log_ui_throttle.get(rid, 0) >= LOG_UI_INTERVAL_SEC:
                                log_ui_throttle[rid] = now
                                res_str = eval_result.result.value
                                if res_str == "PASS":
                                    print(f"[Inspection]  {res_str}  {rid}")
                                else:
                                    miss = eval_result.missing_outputs
                                    print(f"[Inspection]  {res_str}  {rid}" + (f"  (missing: {miss})" if miss else ""))
                except queue.Empty:
                    time.sleep(0.01)

        except KeyboardInterrupt:
            print("\n[Main] Shutdown requested...")
            logger.log_system("INFO", "Shutdown requested via KeyboardInterrupt")

    # ── Cleanup ──
    print("[Main] Stopping workers...")
    control_event.set()

    if dashboard:
        dashboard.close()

    for p in processes:
        p.join(timeout=3)
        if p.is_alive():
            p.terminate()

    logger.stop()
    print("[Main] System shutdown complete.")


if __name__ == "__main__":
    main()

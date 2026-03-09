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

import cv2

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Qt Platform Plugin fix for macOS
if sys.platform == "darwin":
    try:
        import PyQt6
        # Attempt to locate the platforms plugin directory
        pyqt_dir = os.path.dirname(PyQt6.__file__)
        plugin_path = os.path.join(pyqt_dir, "Qt6", "plugins", "platforms")
        if os.path.exists(plugin_path):
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path
    except ImportError:
        pass

from config_loader import load_cameras, load_rules
from camera_worker import camera_worker_process
from dashboard import create_dashboard, HAS_PYQT6
from logic_engine import LogicEngine
from logger import get_logger


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Multi-Camera Manifold Inspection')
    parser.add_argument('--no-display', action='store_true', help='Run without preview')
    parser.add_argument('--cv', action='store_true', help='Force OpenCV dashboard (no PyQt6)')
    # Resolve config dir relative to project root (parent of src/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_config_dir = os.path.join(project_root, 'config')
    parser.add_argument('--config-dir', default=default_config_dir, help='Config directory path')
    args = parser.parse_args()

    # Initialize Logger
    logger = get_logger()
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
        return

    # Defer Logic Engine initialization until manifold is selected

    # ── Multiprocessing setup ──
    ctx = mp.get_context('spawn')
    result_queue = ctx.Queue()
    display_queue = ctx.Queue() if not args.no_display else None
    control_event = ctx.Event()

    processes = []

    # ── Dashboard setup ──
    dashboard = None
    qt_app = None

    if not args.no_display:
        force_cv = args.cv
        dashboard, qt_app = create_dashboard(
            total_rules=0,
            force_cv=force_cv,
            cameras=cameras
        )
        ui_mode = "PyQt6" if qt_app else "OpenCV"
        print(f"[Main] Dashboard initialized ({ui_mode}).")

    inspection_mode = "sequential"  # default
    selected_manifold = "DALIA"     # default
    
    # Wait for mode and manifold selection from integrated Start Pages
    if qt_app:
        print("[Main] Waiting for operator to select Mode and Manifold...")
        from PyQt6.QtCore import QEventLoop
        loop = QEventLoop()
        
        def on_manifold_selected(manifold):
            dashboard.selected_manifold = manifold
            loop.quit()  # Break out of the event loop after both are selected
            
        dashboard.sig_manifold_selected.connect(on_manifold_selected)
        loop.exec()  # Run full Qt event loop to ensure UI is responsive
        
        inspection_mode = getattr(dashboard, 'selected_mode', None)
        selected_manifold = getattr(dashboard, 'selected_manifold', None)
        
        if not inspection_mode or not selected_manifold:
            print("[Main] Operator closed window before completing setup. Exiting.")
            return

    # ── Dynamic Configuration Loading ──
    print(f"\n[Main] Operator Selected: Mode={inspection_mode}, Manifold={selected_manifold}")
    
    # Map manifold to specific rule files
    manifold_rules = {
        "DALIA": "config/DALIA/connectivity_rules.json",
        "Manifold 2": "config/DALIA/connectivity_rules.json", # Default fallback for POC
        "Manifold 3": "config/DALIA/connectivity_rules.json"  # Default fallback for POC
    }
    
    rule_file = manifold_rules.get(selected_manifold, "config/DALIA/connectivity_rules.json")
    
    # Initialize Logic Engine dynamically
    engine = LogicEngine(rule_file)
    total_rules = len(engine.rules)
    print(f"[Main] Logic Engine initialized with {total_rules} rules for {selected_manifold}.")
    logger.log_system("INFO", f"Logic Engine initialized with {total_rules} rules for {selected_manifold}")
    
    # Update camera configs based on Manifold (if they had specific folders, we'd inject it here)
    print("\nCamera → Face Mapping:")
    for cam in cameras:
        status = "✓" if cam.get('enabled', True) else "✗"
        if selected_manifold:
            cam['config'] = f"config/{selected_manifold}/{os.path.basename(cam['config'])}"
        print(f"  [{status}] USB {cam['usb_index']} → Face {cam['face']} → {cam['config']}")
    print()

    # Pass the total rules to dashboard now that we know them
    if dashboard:
        dashboard.progress_bar.setRange(0, total_rules)
        dashboard.progress_bar.setFormat(f"%v / {total_rules} steps")

    # ── Build guided sequence (Sequential mode) ──
    guided_sequence = []
    if inspection_mode == "sequential":
        available_faces = {'A', 'B', 'C', 'D', 'E', 'F'}  # All 6 faces
        guided_sequence = engine.build_guided_sequence(available_faces)
        engine.guided_mode = True
        if guided_sequence:
            engine.set_guided_step(0)
        print(f"[Main] Guided sequence: {len(guided_sequence)} steps (Face F output rules excluded)")

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

        presets = [{
            "width": cam.get("width", 640),
            "height": cam.get("height", 480),
            "fps": cam.get("fps", 30),
            "fourcc": "MJPG"
        }]

        backend = "auto"

        capture_settings = {
            "backend": backend,
            "presets": presets,
            "warmup_reads": 3,
            "robust_mode": True,
            "max_read_retries": 10,
            "target_fps": 30,
            "reject_high_res": False,
            "reject_high_fps": False,
        }
        if cam.get("device_path"):
            capture_settings["device_path"] = cam["device_path"]

        hub_id = cam.get("hub", 0)
        open_semaphore = global_open_semaphore

        # Brief stagger between camera opens
        time.sleep(0.5)
        
        if qt_app:
            qt_app.processEvents() # Keep UI responsive while loading hardware
            
        # Create command queue for this worker
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
                c_queue
            )
        )
        p.start()
        processes.append(p)
        msg = f"Started worker for Face {cam['face']} (USB {cam['usb_index']}, hub {hub_id})"
        print(f"  {msg}")
        logger.log_system("INFO", msg)

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
                    eval_result = engine.add_override(rule_id, "FAIL")
                    if eval_result:
                        logger.log_inspection(eval_result.to_dict())
                        dashboard.update_result(eval_result.to_dict())

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
                # 1. Drain display queue (always — feeds stay live even when paused)
                if display_queue:
                    drained = 0
                    while drained < 5:  # Strict cap to prevent UI freeze
                        try:
                            camera_id, frame = display_queue.get_nowait()
                            dashboard.update_frame(camera_id, frame)
                            drained += 1
                        except queue.Empty:
                            break

                # 2. Drain result queue
                try:
                    result_drained = 0
                    while result_drained < 10: # Strict cap for logic engine
                        result = result_queue.get_nowait()
                        result_drained += 1
                        evaluations = engine.update_state(result)

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
                    try:
                        while True:
                            camera_id, frame = display_queue.get_nowait()
                            dashboard.update_frame(camera_id, frame)
                    except queue.Empty:
                        pass

                    key = dashboard.show()
                    if key == ord('q'):
                        print("\n[Main] Quit requested.")
                        logger.log_system("INFO", "User requested quit")
                        break

                try:
                    while True:
                        result = result_queue.get_nowait()
                        evaluations = engine.update_state(result)
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

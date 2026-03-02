"""
Logging Module

Handles structured logging of inspection results and system events.
Supports both CSV (for Excel analysis) and JSON-lines (for full fidelity).

Features:
- Daily log file rotation
- Structured inspection results
- Camera health audit trail
"""

import os
import json
import csv
import queue
import logging
from datetime import datetime
from threading import Thread
from typing import Dict, Any, Optional

# Constants
LOG_DIR = "logs"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M:%S.%f"

class InspectionLogger:
    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        # Queues for non-blocking logging
        self.log_queue = queue.Queue()
        self.stop_event = False
        
        # Start writer thread
        self.worker_thread = Thread(target=self._writer_loop, daemon=True)
        self.worker_thread.start()
        
        # Configure system logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(os.path.join(log_dir, "system.log")),
                logging.StreamHandler()
            ]
        )
        self.sys_log = logging.getLogger("System")

    def log_inspection(self, result: Dict[str, Any]):
        """
        Log an inspection result (PASS/FAIL).
        """
        self.log_queue.put({
            'type': 'inspection',
            'data': result,
            'timestamp': datetime.now()
        })

    def log_system(self, level: str, message: str):
        """Log a system event (INFO, WARN, ERROR)."""
        self.sys_log.log(getattr(logging, level.upper()), message)

    def stop(self):
        """Stop the logging worker efficiently."""
        self.stop_event = True
        self.worker_thread.join(timeout=2.0)

    def _writer_loop(self):
        """Background thread to write logs to disk."""
        while not self.stop_event or not self.log_queue.empty():
            try:
                item = self.log_queue.get(timeout=0.5)
                timestamp = item['timestamp']
                date_str = timestamp.strftime(DATE_FMT)
                
                # Determine file paths based on date
                json_path = os.path.join(self.log_dir, f"inspection_{date_str}.jsonl")
                csv_path = os.path.join(self.log_dir, f"inspection_{date_str}.csv")
                
                if item['type'] == 'inspection':
                    data = item['data']
                    
                    # 1. Write detailed JSON Line
                    with open(json_path, 'a') as f:
                        entry = {
                            'timestamp': timestamp.isoformat(),
                            **data
                        }
                        f.write(json.dumps(entry) + "\n")
                    
                    # 2. Write summary CSV
                    file_exists = os.path.exists(csv_path)
                    with open(csv_path, 'a', newline='') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow([
                                "Time", "RuleID", "Result", "Input", 
                                "Expected", "Detected", "Missing", "EvalTimeMs"
                            ])
                        
                        writer.writerow([
                            timestamp.strftime(TIME_FMT),
                            data.get('rule_id', ''),
                            data.get('result', ''),
                            data.get('input_hole', ''),
                            "|".join(data.get('expected_outputs', [])),
                            "|".join(data.get('detected_outputs', [])),
                            "|".join(data.get('missing_outputs', [])),
                            data.get('evaluation_time_ms', 0)
                        ])
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Logging error: {e}")

# Global instance
_logger = None

def get_logger(log_dir: str = LOG_DIR) -> InspectionLogger:
    global _logger
    if _logger is None:
        _logger = InspectionLogger(log_dir)
    return _logger

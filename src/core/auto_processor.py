import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF
from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from src.utils.config_manager import ConfigManager


class AutoProcessor(QThread):
    job_grouped = Signal(str, list) # Emits (Group Name, list of file paths)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = ConfigManager()
        self.running = True
        self.mutex = QMutex()
        
        # Pending files dict: {filepath: {"added_at": datetime, "size": (w, h), "priority": int, "processed": bool}}
        self.pending_files = {}
        
    def add_file(self, file_path: str):
        with QMutexLocker(self.mutex):
            p = Path(file_path)
            # Determine priority based on name
            priority = 1
            if "URGENT" in p.name.upper():
                priority = 10
            elif p.suffix.lower() in [".jpg", ".jpeg", ".png"]:
                priority = 0
                
            self.pending_files[file_path] = {
                "added_at": datetime.now(),
                "size": None, # Will be extracted during grouping
                "priority": priority,
                "processed": False
            }
            
    def _extract_size(self, file_path: str):
        # Extract physical size of the first page to group identical formats
        try:
            doc = fitz.open(file_path)
            if len(doc) > 0:
                rect = doc[0].rect
                doc.close()
                return (round(rect.width, 2), round(rect.height, 2))
        except Exception as e:
            if sys.stdout is not None:
                print(f"Failed to read {file_path}: {e}")
        return (0, 0)
        
    def _is_schedule_met(self):
        enabled = self.config.get("automation", "enable_scheduling")
        if not enabled:
            return True
            
        sched_time = self.config.get("automation", "scheduled_time")
        if not sched_time or ":" not in sched_time:
            return True
            
        try:
            now = datetime.now()
            target_hr, target_min = map(int, sched_time.split(":"))
            # If current time is past the scheduled time today (with a 5 min window to trigger)
            target = now.replace(hour=target_hr, minute=target_min, second=0, microsecond=0)
            if now >= target and now < target + timedelta(minutes=5):
                return True
        except:
            pass
        return False
        
    def run(self):
        while self.running:
            time.sleep(5) # Check every 5 seconds
            
            with QMutexLocker(self.mutex):
                # 1. Update sizes if not done
                for fp, data in self.pending_files.items():
                    if data["size"] is None and not data["processed"]:
                        data["size"] = self._extract_size(fp)
                        
                # 2. Check scheduling
                if not self._is_schedule_met():
                    continue
                    
                # 3. Grouping logic
                delay_minutes = int(self.config.get("automation", "group_delay_minutes") or 0)
                max_files = int(self.config.get("automation", "max_files_per_job") or 50)
                
                # Group by size
                groups = {}
                for fp, data in self.pending_files.items():
                    if data["processed"]:
                        continue
                        
                    # Check delay
                    age = datetime.now() - data["added_at"]
                    if age.total_seconds() < delay_minutes * 60 and data["priority"] < 10:
                        # Wait for delay unless it's high priority
                        continue
                        
                    size_key = data["size"]
                    if size_key not in groups:
                        groups[size_key] = []
                    groups[size_key].append((fp, data["priority"]))
                    
                # 4. Trigger ready groups
                for size_key, files_tuples in groups.items():
                    # Sort by priority (descending)
                    files_tuples.sort(key=lambda x: x[1], reverse=True)
                    
                    # Split by max_files
                    for i in range(0, len(files_tuples), max_files):
                        batch = files_tuples[i:i+max_files]
                        batch_paths = [b[0] for b in batch]
                        
                        group_name = f"AutoJob_{int(time.time())}_{size_key[0]}x{size_key[1]}"
                        
                        # Mark processed
                        for fp in batch_paths:
                            self.pending_files[fp]["processed"] = True
                            
                        self.job_grouped.emit(group_name, batch_paths)
                        
    def stop(self):
        self.running = False
        self.wait()

import os
import time
import shutil
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PySide6.QtCore import QObject, Signal, QThread, QMutex, QMutexLocker

class HotFolderSignals(QObject):
    # Emits the path of the ready job folder or file
    new_job_ready = Signal(str)

class NewJobHandler(FileSystemEventHandler):
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor

    def on_created(self, event):
        # We only care about root level items in the Input directory being created.
        path = Path(event.src_path)
        if path.parent == self.monitor.input_path:
            self.monitor.add_pending_item(path)
            
    def on_moved(self, event):
        path = Path(event.dest_path)
        if path.parent == self.monitor.input_path:
            self.monitor.add_pending_item(path)

class StabilizationThread(QThread):
    def __init__(self, monitor):
        super().__init__()
        self.monitor = monitor
        self.running = True
        
    def run(self):
        while self.running:
            self.monitor.process_pending_items()
            time.sleep(1)
            
    def stop(self):
        self.running = False
        self.wait()

class HotFolderMonitor:
    def __init__(self, input_path: str, processing_path: str):
        self.input_path = Path(input_path)
        self.processing_path = Path(processing_path)
        
        # Create directories if they don't exist
        self.input_path.mkdir(parents=True, exist_ok=True)
        self.processing_path.mkdir(parents=True, exist_ok=True)
        
        self.signals = HotFolderSignals()
        
        self.observer = None
        self.handler = NewJobHandler(self)
        
        # Dictionary to track pending items: {Path: {"last_size": int, "stable_count": int}}
        self.pending_items = {}
        self.mutex = QMutex()
        
        self.stabilization_thread = StabilizationThread(self)
        
    def start(self):
        if not self.observer:
            self.observer = Observer()
            # Non-recursive because we only care about top-level drops
            self.observer.schedule(self.handler, str(self.input_path), recursive=False)
            self.observer.start()
            self.stabilization_thread.start()
            
    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        self.stabilization_thread.stop()
            
    def add_pending_item(self, path: Path):
        with QMutexLocker(self.mutex):
            if path not in self.pending_items:
                self.pending_items[path] = {"last_size": -1, "stable_count": 0}
                
    def get_size(self, path: Path):
        if path.is_file():
            try:
                return path.stat().st_size
            except:
                return -1
        elif path.is_dir():
            total_size = 0
            try:
                for dirpath, _, filenames in os.walk(path):
                    for f in filenames:
                        fp = Path(dirpath) / f
                        if not fp.is_symlink():
                            total_size += fp.stat().st_size
                return total_size
            except:
                return -1
        return -1
        
    def process_pending_items(self):
        with QMutexLocker(self.mutex):
            items_to_remove = []
            
            for path, data in self.pending_items.items():
                if not path.exists():
                    items_to_remove.append(path)
                    continue
                    
                current_size = self.get_size(path)
                if current_size == -1:
                    # Could not read size, maybe locked, reset stable count
                    data["stable_count"] = 0
                    continue
                    
                if current_size == data["last_size"]:
                    data["stable_count"] += 1
                else:
                    data["last_size"] = current_size
                    data["stable_count"] = 0
                    
                # If stable for 2 seconds (2 iterations) and size > 0 (or empty dir)
                if data["stable_count"] >= 2:
                    if self._try_move_to_processing(path):
                        items_to_remove.append(path)
                    else:
                        # Reset if move failed (e.g., file still locked by OS)
                        data["stable_count"] = 0
                        
            for path in items_to_remove:
                del self.pending_items[path]
                
    def _try_move_to_processing(self, path: Path) -> bool:
        try:
            # Generate a unique name in Processing
            dest_name = path.name
            dest_path = self.processing_path / dest_name
            
            counter = 1
            while dest_path.exists():
                if path.is_file():
                    dest_path = self.processing_path / f"{path.stem}_{counter}{path.suffix}"
                else:
                    dest_path = self.processing_path / f"{path.name}_{counter}"
                counter += 1
                
            shutil.move(str(path), str(dest_path))
            
            # Emit signal
            self.signals.new_job_ready.emit(str(dest_path))
            return True
            
        except Exception as e:
            print(f"Failed to move {path}: {e}")
            return False

import asyncio
import threading
from typing import List, Optional
from pathlib import Path
from uuid import UUID
from PySide6.QtCore import QThread, Signal

from src.core.processors.worker_pool import WorkerPoolManager
from src.core.models.domain import JobSettings, FileItem, Sheet


class WorkerPoolThread(QThread):
    """
    QThread wrapper for WorkerPoolManager to run its asyncio loop alongside PySide6.
    """
    job_started = Signal(str)
    job_completed = Signal(str, list, list)  # uuid_str, files, sheets
    job_failed = Signal(str, str)  # uuid_str, error_msg

    def __init__(self, parent=None, max_workers: Optional[int] = None):
        super().__init__(parent)
        self.max_workers = max_workers
        self.pool_manager: Optional[WorkerPoolManager] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.ready_event = threading.Event()

    def run(self):
        # Set up new asyncio loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.pool_manager = WorkerPoolManager(max_workers=self.max_workers)
        self.pool_manager.on_job_completed = self._on_job_completed

        # Schedule start() to run once the loop is actually running,
        # then signal readiness to the main thread.
        self.loop.call_soon(self._start_pool)

        try:
            self.loop.run_forever()
        finally:
            if self.pool_manager is not None:
                self.loop.run_until_complete(self.pool_manager.stop())
            self.loop.close()

    def _start_pool(self):
        """Called inside the running event loop."""
        if self.pool_manager is not None:
            self.pool_manager.start()
        self.ready_event.set()

    def submit_job(self, job_id: UUID, file_paths: List[Path], settings: JobSettings):
        """Thread-safe submission from main UI thread."""
        self.ready_event.wait()
        if self.pool_manager is None or self.loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self.pool_manager.submit_job(job_id, file_paths, settings),
            self.loop
        )
        self.job_started.emit(str(job_id))

    def _on_job_completed(self, job_id: UUID, result, error: Exception):
        """Called by WorkerPoolManager when job finishes (in asyncio thread)."""
        if error:
            self.job_failed.emit(str(job_id), str(error))
        else:
            files, sheets = result
            self.job_completed.emit(str(job_id), files, sheets)

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait()

import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Optional
from uuid import UUID

from loguru import logger
from PySide6.QtCore import QThread, Signal

from src.core.models.domain import FileItem, JobSettings
from src.core.processors.worker_pool import WorkerPoolManager


class WorkerPoolThread(QThread):
    """
    QThread wrapper for WorkerPoolManager to run its asyncio loop alongside PySide6.
    """
    job_started = Signal(str)
    job_completed = Signal(str, list)  # uuid_str, files
    job_failed = Signal(str, str)  # uuid_str, error_msg

    finalize_completed = Signal(str, list)  # uuid_str, sheets
    finalize_failed = Signal(str, str)  # uuid_str, error_msg

    # Bound on how long the UI thread waits for the worker pool to come up.
    # Generous: starting a ProcessPoolExecutor on Windows is slow on a loaded
    # machine. The point is to fail with a message rather than freeze for ever.
    _POOL_READY_TIMEOUT = 30.0

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
        self.pool_manager.on_finalize_completed = self._on_finalize_completed

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

    def _await_pool(self, what: str) -> bool:
        """Waits for the worker pool, bounded. Returns False (and says why) if
        it never came up.

        This is called from the UI thread. An unbounded wait() froze the whole
        window with no message whenever the pool failed to start, and the
        `pool_manager is None` fallback returned silently — the job simply
        vanished. Both now surface as an explicit failure.
        """
        if not self.ready_event.wait(timeout=self._POOL_READY_TIMEOUT):
            logger.error(
                f"{what} : le pool de workers n'a pas démarré en "
                f"{self._POOL_READY_TIMEOUT:.0f} s"
            )
            return False
        if self.pool_manager is None or self.loop is None:
            logger.error(f"{what} : pool de workers indisponible")
            return False
        return True

    def submit_job(
        self,
        job_id: UUID,
        file_paths: List[Path],
        settings: JobSettings,
        quantities: Optional[Dict[str, int]] = None,
        priority: int = 2,
    ):
        """Thread-safe submission of one chunk from the main UI thread.

        `quantities` (path string -> quantity) lets the caller override a
        specific file's FileItem.quantity, e.g. to print several copies of
        one file on the sheet — see job_processor.process_job_files.
        `priority`: 0 = Urgente, 1 = Haute, 2 = Normale (see WorkerPoolManager).
        """
        if not self._await_pool(f"Job {job_id}"):
            self.job_failed.emit(
                str(job_id),
                "Le moteur de traitement n'a pas démarré. Redémarrez l'application.",
            )
            return
        asyncio.run_coroutine_threadsafe(
            self.pool_manager.submit_job(
                job_id, file_paths, settings, quantities, priority=priority
            ),
            self.loop
        )
        self.job_started.emit(str(job_id))

    def submit_finalize(
        self, job_id: UUID, file_items: List[FileItem], settings: JobSettings, job_name: Optional[str] = None
    ):
        """Thread-safe submission of the nesting/layout/export step for a whole
        logical job, once all of its chunks have completed."""
        if not self._await_pool(f"Finalisation {job_id}"):
            self.finalize_failed.emit(
                str(job_id),
                "Le moteur de traitement n'a pas démarré. Redémarrez l'application.",
            )
            return
        asyncio.run_coroutine_threadsafe(
            self.pool_manager.submit_finalize_job(job_id, file_items, settings, job_name),
            self.loop
        )

    def _on_job_completed(self, job_id: UUID, result, error: Exception):
        """Called by WorkerPoolManager when a chunk finishes (in asyncio thread)."""
        if error:
            self.job_failed.emit(str(job_id), str(error))
        else:
            self.job_completed.emit(str(job_id), result)

    def _on_finalize_completed(self, job_id: UUID, result, error: Exception):
        """Called by WorkerPoolManager when a logical job's sheets are finalized."""
        if error:
            self.finalize_failed.emit(str(job_id), str(error))
        else:
            self.finalize_completed.emit(str(job_id), result)

    def stop(self):
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.wait()

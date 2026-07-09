import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, List, Optional
from uuid import UUID

from src.core.models.domain import FileItem, JobSettings, Sheet
from src.core.processors.job_processor import finalize_job_sheets, process_job_files

logger = logging.getLogger(__name__)


class WorkerPoolManager:
    """
    Manages the concurrent execution of Jobs using a ProcessPoolExecutor.
    Includes asyncio Queues to handle incoming work asynchronously, on two
    separate tracks:

    - process_job_files (per chunk): import/preflight/correction, independent
      per file, so this is what actually benefits from being split across
      workers for large jobs.
    - finalize_job_sheets (once per logical job): nesting/layout/export, which
      needs the combined FileItems of every chunk to pack sheets well — see
      job_processor.finalize_job_sheets for why this must not run per chunk.
    """

    def __init__(self, max_workers: int = None):
        """
        Initializes the Worker Pool Manager.

        Args:
            max_workers (int, optional): The maximum number of concurrent workers.
                Defaults to CPU_COUNT - 1 (leaves 1 core for UI/Main thread).
        """
        if max_workers is None:
            # Leave one core free for the UI and main DB thread
            max_workers = max(1, multiprocessing.cpu_count() - 1)

        self.max_workers = max_workers
        self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.finalize_queue: asyncio.Queue = asyncio.Queue()
        self.is_running = False
        self._dispatcher_task = None
        self._finalize_dispatcher_task = None

        # Callback triggered when a chunk finishes: (job_id: UUID, result: List[FileItem], error: Exception)
        self.on_job_completed: Callable[[UUID, List[FileItem], Exception], None] = None
        # Callback triggered when a logical job's sheets are finalized: (job_id: UUID, result: List[Sheet], error: Exception)
        self.on_finalize_completed: Callable[[UUID, List[Sheet], Exception], None] = None

    def start(self):
        """Starts the background dispatcher loops."""
        if self.is_running:
            return
        self.is_running = True
        self._dispatcher_task = asyncio.create_task(self._dispatcher_loop())
        self._finalize_dispatcher_task = asyncio.create_task(self._finalize_dispatcher_loop())
        logger.info(f"WorkerPoolManager started with {self.max_workers} workers.")

    async def stop(self):
        """Stops the dispatchers and shuts down the executor."""
        self.is_running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
        if self._finalize_dispatcher_task:
            self._finalize_dispatcher_task.cancel()
        self.executor.shutdown(wait=True)
        logger.info("WorkerPoolManager stopped.")

    async def submit_job(self, job_id: UUID, file_paths: List[Path], settings: JobSettings):
        """
        Submits a chunk of files (import/preflight/correction) to the queue.
        """
        await self.queue.put((job_id, file_paths, settings))
        logger.debug(f"Job {job_id} queued. Queue size: {self.queue.qsize()}")

    async def submit_finalize_job(
        self, job_id: UUID, file_items: List[FileItem], settings: JobSettings, job_name: Optional[str] = None
    ):
        """
        Submits a logical job's combined FileItems for nesting/layout/export,
        once every chunk of that job has completed.
        """
        await self.finalize_queue.put((job_id, file_items, settings, job_name))
        logger.debug(f"Finalize {job_id} queued. Queue size: {self.finalize_queue.qsize()}")

    async def _dispatcher_loop(self):
        """
        Continuously pulls chunks from the queue and dispatches them to the ProcessPool.
        """
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                # Wait for the next job in the queue
                job_id, file_paths, settings = await self.queue.get()

                logger.info(f"Dispatching Job {job_id} to worker pool...")

                # We do not `await` the executor directly here because we want to
                # dispatch multiple jobs up to the worker limit concurrently.
                # Instead, we create a task that awaits the executor.
                asyncio.create_task(self._execute_job(loop, job_id, file_paths, settings))

                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dispatcher loop: {e}")

    async def _execute_job(self, loop, job_id: UUID, file_paths: List[Path], settings: JobSettings):
        """
        Executes a single chunk in the process pool and triggers the callback.
        """
        try:
            # Run the synchronous CPU-bound task in the process pool
            result: List[FileItem] = await loop.run_in_executor(
                self.executor, process_job_files, job_id, file_paths, settings
            )

            # Trigger success callback
            if self.on_job_completed:
                # Assuming callback might be a normal function, we call it.
                # If it's a coroutine, we should await it, but let's assume it's synchronous DB update.
                self.on_job_completed(job_id, result, None)

        except Exception as e:
            logger.error(f"Job {job_id} failed in worker: {e}")
            if self.on_job_completed:
                self.on_job_completed(job_id, [], e)

    async def _finalize_dispatcher_loop(self):
        """
        Continuously pulls finalize requests from the queue and dispatches
        them to the ProcessPool.
        """
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                job_id, file_items, settings, job_name = await self.finalize_queue.get()

                logger.info(f"Dispatching finalize for Job {job_id} to worker pool...")
                asyncio.create_task(self._execute_finalize(loop, job_id, file_items, settings, job_name))

                self.finalize_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in finalize dispatcher loop: {e}")

    async def _execute_finalize(
        self, loop, job_id: UUID, file_items: List[FileItem], settings: JobSettings, job_name: Optional[str]
    ):
        """
        Executes nesting/layout/export for a whole logical job in the process
        pool and triggers the callback.
        """
        try:
            result: List[Sheet] = await loop.run_in_executor(
                self.executor, finalize_job_sheets, job_id, file_items, settings, job_name
            )
            if self.on_finalize_completed:
                self.on_finalize_completed(job_id, result, None)
        except Exception as e:
            logger.error(f"Finalize for job {job_id} failed in worker: {e}")
            if self.on_finalize_completed:
                self.on_finalize_completed(job_id, [], e)

import asyncio
import logging
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, List
from uuid import UUID

from src.core.models.domain import FileItem, JobSettings
from src.core.processors.job_processor import process_job_files

logger = logging.getLogger(__name__)


class WorkerPoolManager:
    """
    Manages the concurrent execution of Jobs using a ProcessPoolExecutor.
    Includes an asyncio Queue to handle incoming jobs asynchronously.
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
        self.is_running = False
        self._dispatcher_task = None

        # Callback triggered when a job finishes: (job_id: UUID, items: List[FileItem], error: Exception)
        self.on_job_completed: Callable[[UUID, List[FileItem], Exception], None] = None

    def start(self):
        """Starts the background dispatcher loop."""
        if self.is_running:
            return
        self.is_running = True
        self._dispatcher_task = asyncio.create_task(self._dispatcher_loop())
        logger.info(f"WorkerPoolManager started with {self.max_workers} workers.")

    async def stop(self):
        """Stops the dispatcher and shuts down the executor."""
        self.is_running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
        self.executor.shutdown(wait=True)
        logger.info("WorkerPoolManager stopped.")

    async def submit_job(self, job_id: UUID, file_paths: List[Path], settings: JobSettings):
        """
        Submits a job to the queue.
        """
        await self.queue.put((job_id, file_paths, settings))
        logger.debug(f"Job {job_id} queued. Queue size: {self.queue.qsize()}")

    async def _dispatcher_loop(self):
        """
        Continuously pulls jobs from the queue and dispatches them to the ProcessPool.
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
        Executes a single job in the process pool and triggers the callback.
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

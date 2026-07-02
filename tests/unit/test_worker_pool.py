import asyncio
from uuid import uuid4

import pytest

from src.core.models.domain import JobSettings
from src.core.processors.worker_pool import WorkerPoolManager


@pytest.fixture
def mock_job_settings():
    return JobSettings()


@pytest.fixture
def temp_pdf(tmp_path):
    import fitz  # PyMuPDF

    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=420, height=595)  # A5 roughly
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(1, 1, 1))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.asyncio
async def test_worker_pool_dispatch(temp_pdf, mock_job_settings):
    """
    Tests that WorkerPoolManager can process a job with an actual file asynchronously.
    """
    # Create the worker pool manager
    manager = WorkerPoolManager(max_workers=2)

    # We will use a future to track when the callback is called
    callback_called = asyncio.Future()

    def mock_callback(job_id, items, error):
        if not callback_called.done():
            callback_called.set_result((job_id, items, error))

    manager.on_job_completed = mock_callback

    # Start the manager
    manager.start()

    # Submit a job
    test_job_id = uuid4()
    await manager.submit_job(job_id=test_job_id, file_paths=[temp_pdf], settings=mock_job_settings)

    # Wait for the callback with a timeout
    try:
        job_id, result, error = await asyncio.wait_for(callback_called, timeout=5.0)
    finally:
        await manager.stop()

    assert error is None
    assert job_id == test_job_id

    items, sheets = result
    assert len(items) == 1
    assert items[0].job_id == test_job_id
    assert items[0].path == temp_pdf

    # Check sheets (it should have generated 1 sheet)
    assert len(sheets) == 1

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
    # Blank page, no drawing operators — this test is about dispatch plumbing,
    # not color correction, so keep it free of RGB-filled vector content
    # (draw_rect(..., color=..., fill=...) emits rg/RG operators, which would
    # legitimately get flagged and corrected to CMYK by the real pipeline).
    doc.new_page(width=420, height=595)  # A5 roughly
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.asyncio
async def test_worker_pool_dispatch(temp_pdf, mock_job_settings):
    """
    Tests that WorkerPoolManager can process a chunk with an actual file
    asynchronously. Nesting/layout/export no longer happen here — see
    test_worker_pool_finalize_dispatch for that step.
    """
    manager = WorkerPoolManager(max_workers=2)

    callback_called = asyncio.Future()

    def mock_callback(job_id, items, error):
        if not callback_called.done():
            callback_called.set_result((job_id, items, error))

    manager.on_job_completed = mock_callback
    manager.start()

    test_job_id = uuid4()
    await manager.submit_job(job_id=test_job_id, file_paths=[temp_pdf], settings=mock_job_settings)

    try:
        job_id, items, error = await asyncio.wait_for(callback_called, timeout=5.0)
    finally:
        await manager.stop()

    assert error is None
    assert job_id == test_job_id
    assert len(items) == 1
    assert items[0].job_id == test_job_id
    assert items[0].path == temp_pdf


@pytest.mark.asyncio
async def test_worker_pool_finalize_dispatch(temp_pdf, mock_job_settings):
    """
    Tests that WorkerPoolManager can nest/layout/export a logical job's
    combined FileItems (the finalize step, run once per job after every
    chunk's process_job_files() has completed).
    """
    manager = WorkerPoolManager(max_workers=2)

    process_done = asyncio.Future()
    finalize_done = asyncio.Future()

    def on_job_completed(job_id, items, error):
        if not process_done.done():
            process_done.set_result((job_id, items, error))

    def on_finalize_completed(job_id, sheets, error):
        if not finalize_done.done():
            finalize_done.set_result((job_id, sheets, error))

    manager.on_job_completed = on_job_completed
    manager.on_finalize_completed = on_finalize_completed
    manager.start()

    test_job_id = uuid4()
    try:
        await manager.submit_job(job_id=test_job_id, file_paths=[temp_pdf], settings=mock_job_settings)
        _, items, error = await asyncio.wait_for(process_done, timeout=5.0)
        assert error is None

        await manager.submit_finalize_job(
            job_id=test_job_id, file_items=items, settings=mock_job_settings, job_name="Test Job"
        )
        job_id, sheets, error = await asyncio.wait_for(finalize_done, timeout=5.0)
    finally:
        await manager.stop()

    assert error is None
    assert job_id == test_job_id
    assert len(sheets) == 1
    assert sheets[0].export_path is not None
    assert sheets[0].export_path.exists()

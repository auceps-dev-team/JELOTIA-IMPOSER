import asyncio
import os
import shutil
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from PIL import Image

from src.core.models.domain import JobSettings
from src.core.processors.worker_pool import WorkerPoolManager
from src.utils.config import config


@pytest.fixture
def temp_dirs(tmp_path):
    # Setup temp dirs
    input_dir = tmp_path / "input"
    processing_dir = tmp_path / "processing"
    output_dir = tmp_path / "output"

    input_dir.mkdir()
    processing_dir.mkdir()
    output_dir.mkdir()

    # Override config
    original_input = config.input_dir
    original_processing = config.processing_dir
    original_output = config.output_dir

    config.input_dir = input_dir
    config.processing_dir = processing_dir
    config.output_dir = output_dir

    yield input_dir, processing_dir, output_dir

    # Restore config
    config.input_dir = original_input
    config.processing_dir = original_processing
    config.output_dir = original_output


def generate_test_files(count: int, input_dir: Path) -> list[Path]:
    paths = []
    # Create 1 base PDF and 1 base image, then copy them to save time
    base_pdf = input_dir / "base.pdf"
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(fitz.Rect(10, 10, 90, 90), color=(1, 0, 0), fill=(0, 1, 0))
    doc.save(str(base_pdf))
    doc.close()

    base_img = input_dir / "base.jpg"
    img = Image.new("RGB", (100, 100), color="red")
    img.save(base_img)

    for i in range(count):
        target = input_dir / f"test_file_{i}.pdf" if i % 2 == 0 else input_dir / f"test_file_{i}.jpg"
        source = base_pdf if i % 2 == 0 else base_img
        shutil.copy(source, target)
        paths.append(target)
        
    return paths


@pytest.mark.asyncio
async def test_end_to_end_worker_pool(temp_dirs):
    input_dir, processing_dir, output_dir = temp_dirs
    
    # We want to test E2E with 50 files instead of 500 in unit test mode to avoid timeouts
    count = 50
    files = generate_test_files(count, input_dir)
    
    settings = JobSettings(
        sheet_width_mm=1000.0,
        sheet_height_mm=1000.0,
        gap_mm=5.0,
        allow_rotation=True,
        export_format="PDF/X-1a"
    )
    
    pool = WorkerPoolManager(max_workers=4)
    pool.start()
    
    job_id = uuid4()
    
    # Use asyncio.Event to wait for completion
    completion_event = asyncio.Event()
    final_items = []
    final_sheets = []
    
    def on_job_completed(jid, result, error):
        nonlocal final_items, final_sheets
        if error:
            print(f"Job failed: {error}")
        items, sheets = result
        final_items = items
        final_sheets = sheets
        completion_event.set()
        
    pool.on_job_completed = on_job_completed
    
    await pool.submit_job(job_id, files, settings)
    
    # Wait with timeout
    await asyncio.wait_for(completion_event.wait(), timeout=60.0)
    
    await pool.stop()
    
    assert len(final_items) == count
    assert len(final_sheets) > 0
    
    # Verify export
    for sheet in final_sheets:
        assert sheet.export_path is not None
        assert sheet.export_path.exists()
        assert sheet.export_path.suffix == ".pdf"


@pytest.mark.asyncio
async def test_end_to_end_multiple_jobs(temp_dirs):
    input_dir, processing_dir, output_dir = temp_dirs
    pool = WorkerPoolManager(max_workers=8)
    pool.start()
    
    settings = JobSettings(
        sheet_width_mm=1000.0,
        sheet_height_mm=1000.0,
        gap_mm=5.0,
        allow_rotation=True,
    )
    
    # Submit 5 jobs of 10 files each
    job_ids = [uuid4() for _ in range(5)]
    files = generate_test_files(10, input_dir)
    
    completed = 0
    event = asyncio.Event()
    
    def on_job_completed(jid, result, error):
        nonlocal completed
        completed += 1
        if completed == 5:
            event.set()
            
    pool.on_job_completed = on_job_completed
    
    for jid in job_ids:
        await pool.submit_job(jid, files, settings)
        
    await asyncio.wait_for(event.wait(), timeout=60.0)
    await pool.stop()
    
    assert completed == 5

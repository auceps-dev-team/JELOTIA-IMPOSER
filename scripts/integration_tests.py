import asyncio
import logging
import uuid
from pathlib import Path

import fitz

from src.core.models.domain import JobSettings
from src.core.processors.job_processor import process_job_files
from src.core.processors.worker_pool import WorkerPoolManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("IntegrationTests")

def create_mock_pdf(path: Path, width_mm: float, height_mm: float, corrupt: bool = False):
    if corrupt:
        path.write_text("This is not a PDF file, it is corrupted text.")
        return
    
    doc = fitz.open()
    # 1 point = 1/72 inch. 1 mm = 2.83465 points
    w_pt = width_mm * 2.83465
    h_pt = height_mm * 2.83465
    page = doc.new_page(width=w_pt, height=h_pt)
    page.draw_rect(page.rect, color=(0,0,0), fill=(0.8, 0.8, 0.8))
    doc.save(str(path))
    doc.close()

async def run_tests():
    test_dir = Path("integration_test_data")
    test_dir.mkdir(exist_ok=True)
    
    logger.info("=== STARTING INTEGRATION TESTS ===")
    
    # 1. Module 1.1 & 1.2 & 1.3 tests
    logger.info("--- Test 1: Fichiers PDF sains vs corrompus & Preflight ---")
    healthy_pdf = test_dir / "healthy.pdf"
    corrupt_pdf = test_dir / "corrupt.pdf"
    create_mock_pdf(healthy_pdf, 100, 150)
    create_mock_pdf(corrupt_pdf, 100, 150, corrupt=True)
    
    settings = JobSettings(
        sheet_width_mm=1000, 
        sheet_height_mm=700, 
        force_cmyk=True, # triggers correction
    )
    
    # Test corrupt
    logger.info("Testing Corrupt PDF...")
    try:
        process_job_files(uuid.uuid4(), [str(corrupt_pdf)], settings)
    except Exception as e:
        logger.info(f"Expected Error Caught: {e}")

    # Test healthy
    logger.info("Testing Healthy PDF + Correction (CMYK)...")
    try:
        items, sheets = process_job_files(uuid.uuid4(), [str(healthy_pdf)], settings)
        logger.info(f"Healthy PDF Preflight Status: {items[0].preflight_status}")
    except Exception as e:
        logger.error(f"Failed healthy pdf: {e}")

    # 2. Module 1.4: Stress test 100 fichiers virtuels
    logger.info("--- Test 2: Stress test 100 fichiers virtuels via WorkerPool ---")
    pool = WorkerPoolManager(max_workers=4)
    
    def on_job_completed(job_id, result, error):
        if error:
            logger.error(f"Job {job_id} failed: {error}")
        else:
            items, sheets = result
            logger.info(f"Job {job_id} completed successfully. Processed {len(items)} items. Generated {len(sheets)} sheets.")
            if sheets:
                logger.info(f"  -> Best sheet fill rate: {max(s.fill_rate for s in sheets):.2f}%")
            
    pool.on_job_completed = on_job_completed
    pool.start()
    
    # Generate 100 small pdfs
    stress_pdfs = []
    for i in range(100):
        p = test_dir / f"stress_{i}.pdf"
        create_mock_pdf(p, 50, 50)
        stress_pdfs.append(p)
        
    job_id = uuid.uuid4()
    logger.info("Submitting 100 files to worker pool...")
    await pool.submit_job(job_id, [str(p) for p in stress_pdfs], settings)
    
    logger.info("Waiting for stress test to finish (approx 5-10s)...")
    await asyncio.sleep(5) # Let pool process
    await pool.stop()
    
    logger.info("=== INTEGRATION TESTS FINISHED ===")

if __name__ == "__main__":
    asyncio.run(run_tests())

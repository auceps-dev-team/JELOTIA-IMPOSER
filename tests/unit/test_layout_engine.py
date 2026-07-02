import uuid
from pathlib import Path

import fitz
import pytest

from src.core.engines.layout_engine import LayoutEngine
from src.core.models.domain import FileItem, JobSettings, PlacedItem, PreflightStatus, Sheet, ColorMode


@pytest.fixture
def temp_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(1, 0, 0)) # Red square
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_generate_sheet_pdf(tmp_path, temp_pdf):
    engine = LayoutEngine()
    
    settings = JobSettings(
        sheet_width_mm=500,
        sheet_height_mm=500,
        draw_cutlines=True,
        add_crop_marks=True
    )
    
    file_item = FileItem(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        path=temp_pdf,
        width_mm=100,
        height_mm=100,
        format="PDF",
        dpi=300,
        color_mode=ColorMode.CMYK,
        quantity=1,
        preflight_status=PreflightStatus.OK
    )
    
    placed_item = PlacedItem(
        file_item_id=file_item.id,
        source_path=file_item.path,
        x_mm=50,
        y_mm=50,
        width_mm=100,
        height_mm=100,
        rotated=False
    )
    
    sheet = Sheet(
        id=uuid.uuid4(),
        job_id=file_item.job_id,
        sheet_number=1,
        width_mm=500,
        height_mm=500,
        items=[placed_item]
    )
    
    export_dir = tmp_path / "exports"
    
    # Generate the PDF
    pdf_path = engine.generate_sheet_pdf(file_item.job_id, sheet, settings, export_dir)
    
    assert pdf_path.exists()
    
    # Verify the generated PDF
    doc = fitz.open(str(pdf_path))
    assert len(doc) == 1
    
    page = doc[0]
    # Check page size (500mm * 2.83465 ~= 1417.3 pts)
    assert abs(page.rect.width - 500 * 2.83465) < 1.0
    assert abs(page.rect.height - 500 * 2.83465) < 1.0
    
    doc.close()

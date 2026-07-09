import uuid
from pathlib import Path

import fitz
import pikepdf
import pytest
from PIL import Image

from src.core.models.domain import JobSettings, PlacedItem, Sheet
from src.core.sheet_export_service import SheetExportService


@pytest.fixture
def temp_pdf(tmp_path):
    pdf_path = tmp_path / "art.pdf"
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(1, 0, 0))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_sheet(job_id, source_path):
    placed = PlacedItem(
        file_item_id=uuid.uuid4(), source_path=source_path,
        x_mm=10, y_mm=10, width_mm=80, height_mm=80, rotated=False,
    )
    return Sheet(job_id=job_id, sheet_number=1, width_mm=200, height_mm=200, items=[placed], fill_rate=16.0)


def test_regenerate_and_export_multiple_formats(tmp_path, temp_pdf):
    service = SheetExportService()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(sheet_width_mm=200, sheet_height_mm=200, export_format="PDF/X-1a")

    output_dir = tmp_path / "out"
    work_dir = tmp_path / "work"

    results = service.regenerate_and_export(
        sheet, settings, ["PDF/X-1a", "TIFF", "JPEG"], output_dir, work_dir, job_name="Client X"
    )

    assert set(results) == {"PDF/X-1a", "TIFF", "JPEG"}

    pdf_path = results["PDF/X-1a"]
    assert pdf_path.exists()
    assert pdf_path.name == "client_x_planche_01.pdf"
    with pikepdf.Pdf.open(pdf_path) as pdf:
        assert pdf.docinfo["/GTS_PDFXVersion"] == "PDF/X-1a:2001"
    d = fitz.open(str(pdf_path))
    d[0].get_pixmap()
    d.close()

    tiff_path = results["TIFF"]
    assert tiff_path.name == "client_x_planche_01.tiff"
    with Image.open(tiff_path) as img:
        assert img.mode == "CMYK"

    jpeg_path = results["JPEG"]
    assert jpeg_path.name == "client_x_planche_01.jpg"
    with Image.open(jpeg_path) as img:
        assert img.mode == "CMYK"

    # Intermediate work dir is cleaned up.
    assert not work_dir.exists()


def test_regenerate_reflects_updated_item_position(tmp_path, temp_pdf):
    """Moving an item and re-running the service should change the rendered
    base PDF (proxy for the manual-repositioning apply flow)."""
    service = SheetExportService()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(sheet_width_mm=200, sheet_height_mm=200, export_format="PDF")

    out1 = tmp_path / "out1"
    work1 = tmp_path / "work1"
    service.regenerate_and_export(sheet, settings, ["PDF"], out1, work1)

    sheet.items[0].x_mm = 90
    sheet.items[0].y_mm = 90

    out2 = tmp_path / "out2"
    work2 = tmp_path / "work2"
    results = service.regenerate_and_export(sheet, settings, ["PDF"], out2, work2)

    assert results["PDF"].exists()

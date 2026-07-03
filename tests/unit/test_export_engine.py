import os
import shutil
from pathlib import Path
from uuid import uuid4

import fitz
import pikepdf
import pytest
from PIL import Image

from src.core.engines.export_engine import ExportEngine
from src.core.models.domain import JobSettings, Sheet


@pytest.fixture
def base_pdf_path(tmp_path):
    """Creates a simple valid PDF for testing"""
    pdf_path = tmp_path / "test_base_sheet.pdf"
    doc = fitz.open()
    page = doc.new_page(width=500, height=500)
    page.draw_rect(fitz.Rect(100, 100, 400, 400), color=(1, 0, 0), fill=(0, 1, 0))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def export_engine():
    return ExportEngine()


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "output"
    d.mkdir()
    return d


def test_export_pdfx(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="PDF/X-1a")

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.exists()
    assert result_path.suffix == ".pdf"

    # Verify basic PDF/X metadata injection
    with pikepdf.Pdf.open(result_path) as pdf:
        assert "/OutputIntents" in pdf.Root
        assert "/GTS_PDFXVersion" in pdf.Root.Info


def test_export_tiff(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="TIFF", export_dpi=150)

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.exists()
    assert result_path.suffix == ".tiff"

    # Verify TIFF properties
    with Image.open(result_path) as img:
        assert img.format == "TIFF"
        assert img.mode == "CMYK"


def test_export_jpeg(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=2)
    settings = JobSettings(export_format="JPEG", export_dpi=72)

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.exists()
    assert result_path.suffix == ".jpg"

    # Verify JPEG properties
    with Image.open(result_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "CMYK"

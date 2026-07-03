import os
import shutil
from pathlib import Path
from uuid import uuid4

import fitz
import pikepdf
import pytest
from PIL import Image
from unittest.mock import MagicMock, patch

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


def test_export_pdfx4(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="PDF/X-4")

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.exists()
    assert result_path.suffix == ".pdf"

    # Verify basic PDF/X metadata injection
    with pikepdf.Pdf.open(result_path) as pdf:
        assert "/OutputIntents" in pdf.Root
        assert "/GTS_PDFXVersion" in pdf.Root.Info


def test_export_unknown_format(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="WEBP")

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.exists()
    # It should default to standard copy
    assert result_path.read_bytes() == base_pdf_path.read_bytes()


def test_export_exception(export_engine, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="PDF/X-1a")
    
    # Passing a path that does not exist to force exception
    bad_path = Path("does_not_exist.pdf")

    with pytest.raises(Exception):
        export_engine.export_sheet(job_id, sheet, bad_path, settings, output_dir)


@patch("src.core.engines.export_engine.fitz.open")
def test_export_empty_pdf(mock_fitz_open, export_engine, tmp_path, output_dir):
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 0
    mock_fitz_open.return_value = mock_doc
    
    empty_pdf = tmp_path / "dummy.pdf"
    empty_pdf.touch()
    
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="JPEG")

    with pytest.raises(ValueError, match="Source PDF has no pages"):
        export_engine.export_sheet(job_id, sheet, empty_pdf, settings, output_dir)


@patch("src.core.engines.export_engine.fitz.open")
def test_export_raster_exception(mock_fitz_open, export_engine, tmp_path, output_dir):
    mock_fitz_open.side_effect = Exception("Rasterizer error")
    
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.touch()
    
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="TIFF")

    with pytest.raises(Exception, match="Rasterizer error"):
        export_engine.export_sheet(job_id, sheet, pdf_path, settings, output_dir)



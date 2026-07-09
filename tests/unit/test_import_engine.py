from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from PIL import Image

from src.core.engines.import_engine import ImportEngine
from src.core.models.domain import ColorMode, FileFormat, PreflightErrorType, PreflightStatus


@pytest.fixture
def test_files_dir(tmp_path):
    dir_path = tmp_path / "test_files"
    dir_path.mkdir()
    return dir_path


@pytest.fixture
def dummy_pdf(test_files_dir):
    path = test_files_dir / "test.pdf"
    doc = fitz.open()
    # 1 inch = 72 points
    # 100mm x 150mm => (100 / 25.4) * 72, (150 / 25.4) * 72
    w_pt = (100.0 / 25.4) * 72.0
    h_pt = (150.0 / 25.4) * 72.0

    # 2 pages
    doc.new_page(width=w_pt, height=h_pt)
    doc.new_page(width=w_pt, height=h_pt)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def dummy_image(test_files_dir):
    path = test_files_dir / "test.jpg"
    # Create 300x300 pixel image, CMYK, DPI 300
    # Size in mm should be: (300 / 300) * 25.4 = 25.4mm x 25.4mm
    img = Image.new("CMYK", (300, 300), color=(0, 255, 255, 0))
    img.save(str(path), dpi=(300, 300))
    return path


@pytest.fixture
def dummy_corrupted(test_files_dir):
    path = test_files_dir / "corrupt.pdf"
    path.write_text("This is not a real PDF file")
    return path


def test_process_pdf(dummy_pdf):
    engine = ImportEngine()
    job_id = uuid4()

    items = engine.process_file(job_id, dummy_pdf, min_dpi=300)

    assert len(items) == 2
    item1, item2 = items

    assert item1.job_id == job_id
    assert item1.format == FileFormat.PDF
    assert item1.color_mode == ColorMode.CMYK
    assert item1.dpi == 300
    assert abs(item1.width_mm - 100.0) < 0.1
    assert abs(item1.height_mm - 150.0) < 0.1
    assert item1.preflight_status == PreflightStatus.PENDING
    assert len(item1.preflight_errors) == 0


def test_process_image(dummy_image):
    engine = ImportEngine()
    job_id = uuid4()

    items = engine.process_file(job_id, dummy_image)

    assert len(items) == 1
    item = items[0]

    assert item.format == FileFormat.JPEG
    assert item.color_mode == ColorMode.CMYK
    assert item.dpi == 300
    assert abs(item.width_mm - 25.4) < 0.1
    assert abs(item.height_mm - 25.4) < 0.1
    assert item.preflight_status == PreflightStatus.PENDING


def test_process_corrupted(dummy_corrupted):
    engine = ImportEngine()
    job_id = uuid4()

    items = engine.process_file(job_id, dummy_corrupted)

    assert len(items) == 1
    item = items[0]

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.CORRUPTED
    assert item.preflight_errors[0].is_blocking is True


@pytest.fixture
def vector_rgb_pdf(test_files_dir):
    """A PDF with only vector content filled in DeviceRGB — no embedded raster
    image at all, so get_image_info() alone can never see it."""
    path = test_files_dir / "vector_rgb.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(fitz.Rect(20, 20, 180, 180), color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def vector_cmyk_pdf(test_files_dir):
    """A PDF with only vector content filled in DeviceCMYK (k/K operators)."""
    path = test_files_dir / "vector_cmyk.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(20, 20, 180, 180))
    shape.finish(fill=(0, 1, 1, 0), color=(0, 1, 1, 0))
    shape.commit()
    doc.save(str(path))
    doc.close()
    return path


def test_process_pdf_detects_vector_rgb_content(vector_rgb_pdf):
    """Regression test: vector-only content filled in DeviceRGB (rg/RG
    operators, no embedded image) must be detected as RGB, not silently
    default to CMYK."""
    engine = ImportEngine()
    items = engine.process_file(uuid4(), vector_rgb_pdf, min_dpi=300)

    assert len(items) == 1
    assert items[0].color_mode == ColorMode.RGB


def test_process_pdf_vector_cmyk_not_flagged_as_rgb(vector_cmyk_pdf):
    """No false positive: genuine DeviceCMYK vector fills must stay CMYK."""
    engine = ImportEngine()
    items = engine.process_file(uuid4(), vector_cmyk_pdf, min_dpi=300)

    assert len(items) == 1
    assert items[0].color_mode == ColorMode.CMYK


def test_process_not_found():
    engine = ImportEngine()
    job_id = uuid4()

    items = engine.process_file(job_id, Path("does_not_exist.pdf"))

    assert len(items) == 1
    assert items[0].preflight_status == PreflightStatus.ERROR
    assert "File not found" in items[0].preflight_errors[0].message

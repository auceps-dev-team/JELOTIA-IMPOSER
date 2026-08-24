import uuid

import fitz
import pytest

from src.core.engines.layout_engine import LayoutEngine
from src.core.models.domain import (
    JobSettings,
    PlacedItem,
    Sheet,
)


@pytest.fixture
def temp_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    page.draw_rect(page.rect, color=(0, 0, 0), fill=(1, 0, 0))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _make_sheet(job_id, source_path, sheet_number=1, w=500, h=500):
    placed = PlacedItem(
        file_item_id=uuid.uuid4(),
        source_path=source_path,
        x_mm=50, y_mm=50, width_mm=100, height_mm=100, rotated=False,
    )
    return Sheet(
        id=uuid.uuid4(), job_id=job_id, sheet_number=sheet_number,
        width_mm=w, height_mm=h, items=[placed], fill_rate=40.0,
    )


def test_generate_sheet_pdf_basic(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(sheet_width_mm=500, sheet_height_mm=500, generate_thumbnail=False)

    pdf_path = engine.generate_sheet_pdf(job_id, sheet, settings, tmp_path / "exports")

    assert pdf_path.exists()
    doc = fitz.open(str(pdf_path))
    assert len(doc) == 1
    assert abs(doc[0].rect.width - 500 * 2.83465) < 1.0
    doc.close()


def test_generate_sheet_pdf_with_cutlines(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(
        sheet_width_mm=500, sheet_height_mm=500,
        draw_cutlines=True, add_crop_marks=True, generate_thumbnail=False,
    )
    pdf_path = engine.generate_sheet_pdf(job_id, sheet, settings, tmp_path / "exports")
    assert pdf_path.exists()


def test_generate_thumbnail(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(sheet_width_mm=500, sheet_height_mm=500, generate_thumbnail=True)

    export_dir = tmp_path / "exports"
    pdf_path = engine.generate_sheet_pdf(job_id, sheet, settings, export_dir)
    thumb = engine._generate_thumbnail(pdf_path, export_dir)

    assert thumb is not None
    assert thumb.exists()
    assert thumb.suffix == ".png"
    assert thumb.stat().st_size > 0


def test_process_job_layout_generates_thumbnails(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(sheet_width_mm=500, sheet_height_mm=500, generate_thumbnail=True)

    sheets = engine.process_job_layout(job_id, [sheet], settings, tmp_path / "exports")

    assert sheets[0].export_path is not None
    assert sheets[0].export_path.exists()
    assert sheets[0].thumbnail_path is not None
    assert sheets[0].thumbnail_path.exists()


def test_process_job_layout_cut_layer(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(
        sheet_width_mm=500, sheet_height_mm=500,
        generate_thumbnail=False, separate_cut_layer=True,
    )

    sheets = engine.process_job_layout(job_id, [sheet], settings, tmp_path / "exports")

    assert sheets[0].cut_layer_path is not None
    assert sheets[0].cut_layer_path.exists()
    assert "cutlayer" in sheets[0].cut_layer_path.name

    # Verify it's a valid PDF
    doc = fitz.open(str(sheets[0].cut_layer_path))
    assert len(doc) == 1
    doc.close()


def test_qr_code_embedded(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheet = _make_sheet(job_id, temp_pdf)
    settings = JobSettings(
        sheet_width_mm=500, sheet_height_mm=500,
        add_qr_code=True, qr_code_size_mm=20.0, generate_thumbnail=False,
    )

    pdf_path = engine.generate_sheet_pdf(job_id, sheet, settings, tmp_path / "exports")
    assert pdf_path.exists()

    # QR code presence: the PDF should be larger than one without
    settings_no_qr = JobSettings(
        sheet_width_mm=500, sheet_height_mm=500,
        add_qr_code=False, generate_thumbnail=False,
    )
    sheet2 = _make_sheet(job_id, temp_pdf, sheet_number=2)
    pdf_no_qr = engine.generate_sheet_pdf(job_id, sheet2, settings_no_qr, tmp_path / "exports2")

    assert pdf_path.stat().st_size > pdf_no_qr.stat().st_size


def test_multiple_sheets(tmp_path, temp_pdf):
    engine = LayoutEngine()
    job_id = uuid.uuid4()
    sheets = [_make_sheet(job_id, temp_pdf, i) for i in range(1, 4)]
    settings = JobSettings(sheet_width_mm=500, sheet_height_mm=500, generate_thumbnail=True)

    result = engine.process_job_layout(job_id, sheets, settings, tmp_path / "exports")

    assert len(result) == 3
    for s in result:
        assert s.export_path is not None and s.export_path.exists()
        assert s.thumbnail_path is not None and s.thumbnail_path.exists()


def test_thumbnail_invalid_pdf(tmp_path):
    engine = LayoutEngine()
    bad_path = tmp_path / "not_a_pdf.pdf"
    bad_path.write_bytes(b"not a pdf")
    result = engine._generate_thumbnail(bad_path, tmp_path)
    assert result is None

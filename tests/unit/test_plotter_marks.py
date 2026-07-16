import uuid

import fitz
import pytest

from src.core.engines.layout_engine import LayoutEngine
from src.core.engines.nesting_engine import NestingEngine, ShelfNestingStrategy
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PlacedItem,
    Sheet,
)


def _sheet(width=200.0, height=200.0, items=None):
    return Sheet(
        job_id=uuid.uuid4(), sheet_number=1, width_mm=width, height_mm=height,
        items=items or [], fill_rate=10.0,
    )


def _render(pdf_path, zoom=4.0):
    doc = fitz.open(str(pdf_path))
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    doc.close()
    return pix


def _pixel_mm(pix, x_mm, y_mm, zoom=4.0):
    """RGB at a physical position (mm, origin top-left)."""
    k = 72 / 25.4 * zoom
    return pix.pixel(int(x_mm * k), int(y_mm * k))


@pytest.mark.parametrize("mark_type", ["graphtec2", "graphtec1"])
def test_arms_marks_are_drawn_at_the_four_corners(tmp_path, mark_type):
    settings = JobSettings(
        plotter_marks=mark_type, plotter_mark_margin_mm=5.0,
        plotter_mark_length_mm=15.0, plotter_mark_thickness_mm=1.0,
        draw_cutlines=False, add_crop_marks=False, generate_thumbnail=False,
    )
    sheet = _sheet()
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), sheet, settings, tmp_path)
    pix = _render(out)

    # Both types occupy the band [5, 20] mm from the edges; the arm's line
    # sits at 5 mm (type 2) or 20 mm (type 1) from each edge.
    arm = 5.0 if mark_type == "graphtec2" else 20.0
    mid = 12.5  # somewhere along the arm, inside [5, 20]
    height = 200.0
    # Bottom-left corner (PDF bottom = high y in rendered image space):
    r, g, b = _pixel_mm(pix, mid, height - arm)
    assert max(r, g, b) < 100, f"bras horizontal bas-gauche absent ({r},{g},{b})"
    r, g, b = _pixel_mm(pix, arm, height - mid)
    assert max(r, g, b) < 100, "bras vertical bas-gauche absent"
    # Top-right corner:
    r, g, b = _pixel_mm(pix, 200 - mid, arm)
    assert max(r, g, b) < 100, "bras horizontal haut-droit absent"
    r, g, b = _pixel_mm(pix, 200 - arm, mid)
    assert max(r, g, b) < 100, "bras vertical haut-droit absent"

    # Center of the sheet stays clean.
    r, g, b = _pixel_mm(pix, 100, 100)
    assert min(r, g, b) > 200


def test_nesting_reserves_margin_for_arms_marks():
    """With ARMS marks on, no pose may enter the marks' band (5+15+3 = 23mm)."""
    settings = JobSettings(
        sheet_width_mm=200.0, sheet_height_mm=200.0, gap_mm=2.0,
        margin_mm=0.0, plotter_marks="graphtec2",
        plotter_mark_margin_mm=5.0, plotter_mark_length_mm=15.0,
    )
    items = [
        FileItem(
            job_id=uuid.uuid4(), path=f"x{i}.pdf", format=FileFormat.PDF,
            width_mm=50.0, height_mm=50.0, dpi=300, color_mode=ColorMode.CMYK,
            preflight_status="OK",
        )
        for i in range(4)
    ]
    sheets = NestingEngine(ShelfNestingStrategy()).process(items, settings)

    reserve = settings.plotter_reserve_mm()
    assert reserve == pytest.approx(23.0)
    for sheet in sheets:
        for item in sheet.items:
            assert item.x_mm >= reserve - 1e-6
            assert item.y_mm >= reserve - 1e-6
            assert item.x_mm + item.width_mm <= 200.0 - reserve + 1e-6
            assert item.y_mm + item.height_mm <= 200.0 - reserve + 1e-6


def test_cut_contour_spot_embedded(tmp_path):
    settings = JobSettings(
        cut_contour_spot=True, draw_cutlines=False, add_crop_marks=False,
        generate_thumbnail=False,
    )
    items = [
        PlacedItem(
            file_item_id=uuid.uuid4(), source_path="absent.pdf",
            x_mm=40, y_mm=40, width_mm=60, height_mm=60,
        )
    ]
    sheet = _sheet(items=items)
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), sheet, settings, tmp_path)

    raw = out.read_bytes()
    assert b"CutContour" in raw, "le ton direct CutContour doit être embarqué"
    assert b"Separation" in raw, "CutContour doit être une séparation (spot)"


def test_watermark_stamped_when_set(tmp_path):
    settings = JobSettings(
        watermark_text="NON LICENCIÉ", draw_cutlines=False, add_crop_marks=False,
        generate_thumbnail=False,
    )
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), _sheet(), settings, tmp_path)

    doc = fitz.open(str(out))
    assert "NON LICENCIÉ" in doc[0].get_text(), "le filigrane doit apparaître sur la planche"
    doc.close()


def test_no_watermark_by_default(tmp_path):
    settings = JobSettings(
        draw_cutlines=False, add_crop_marks=False, generate_thumbnail=False
    )
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), _sheet(), settings, tmp_path)
    doc = fitz.open(str(out))
    assert "LICENCIÉ" not in doc[0].get_text()
    doc.close()


def test_no_marks_by_default(tmp_path):
    settings = JobSettings(
        draw_cutlines=False, add_crop_marks=False, generate_thumbnail=False
    )
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), _sheet(), settings, tmp_path)
    pix = _render(out)
    r, g, b = _pixel_mm(pix, 12.5, 200 - 5.0)
    assert min(r, g, b) > 200, "aucune marque ARMS ne doit apparaître par défaut"
    assert b"CutContour" not in out.read_bytes()

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import fitz
import pytest

from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightErrorType,
    PreflightStatus,
)


@pytest.fixture
def default_settings():
    return JobSettings(
        sheet_width_mm=900.0,
        sheet_height_mm=600.0,
        min_dpi=300,
        force_cmyk=True,
    )


@pytest.fixture
def valid_file_item():
    return FileItem(
        job_id=uuid4(),
        path=Path("dummy.jpg"),
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=150.0,
        dpi=300,
        color_mode=ColorMode.CMYK,
    )


def test_preflight_valid_item(valid_file_item, default_settings):
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.OK
    assert len(item.preflight_errors) == 0


def test_preflight_low_resolution(valid_file_item, default_settings):
    valid_file_item.dpi = 150  # Below 300
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.WARNING
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.RESOLUTION_LOW
    assert item.preflight_errors[0].is_blocking is False


def test_preflight_wrong_color_mode(valid_file_item, default_settings):
    valid_file_item.color_mode = ColorMode.RGB
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.WARNING
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.WRONG_COLOR_MODE
    assert item.preflight_errors[0].is_blocking is False


def test_preflight_size_mismatch(valid_file_item, default_settings):
    valid_file_item.width_mm = 1000.0  # Exceeds 900.0
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.SIZE_MISMATCH
    assert item.preflight_errors[0].is_blocking is True


def test_preflight_size_fits_if_rotated(valid_file_item, default_settings):
    # Sheet is 900x600. File is 600x900. Normally exceeds height, but fits if rotated.
    valid_file_item.width_mm = 600.0
    valid_file_item.height_mm = 900.0
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.OK
    assert len(item.preflight_errors) == 0


def test_preflight_multiple_errors(valid_file_item, default_settings):
    valid_file_item.dpi = 72
    valid_file_item.color_mode = ColorMode.RGB
    valid_file_item.width_mm = 2000.0

    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 3

    error_types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.RESOLUTION_LOW in error_types
    assert PreflightErrorType.WRONG_COLOR_MODE in error_types
    assert PreflightErrorType.SIZE_MISMATCH in error_types


# --------------------------------------------------------------------------- #
#  Deep PDF analysis — on REAL files.
#
#  These replace mock-based tests that fed the engine a dictionary PyMuPDF never
#  produces ({"colorspace": 3, "alpha": True}). They passed at 100 % coverage
#  while the engine detected no transparency at all and flagged every CMYK file
#  as transparent. A mock can only confirm what the author already believes.
# --------------------------------------------------------------------------- #

def _pdf_with_image(tmp_path, img, name):
    """A one-page PDF really embedding `img`."""
    import io

    buf = io.BytesIO()
    img.save(buf, format="TIFF" if img.mode == "CMYK" else "PNG")
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(fitz.Rect(20, 20, 280, 280), stream=buf.getvalue())
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def test_preflight_detects_real_transparency(tmp_path, valid_file_item, default_settings):
    """An RGBA image carries a soft mask — PyMuPDF exposes it as `smask`."""
    from PIL import Image

    valid_file_item.format = FileFormat.PDF
    valid_file_item.path = _pdf_with_image(
        tmp_path, Image.new("RGBA", (80, 80), (255, 0, 0, 128)), "rgba.pdf"
    )

    item = PreflightEngine().run_preflight(valid_file_item, default_settings)

    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.TRANSPARENCY_DETECTED in types
    assert item.preflight_status == PreflightStatus.WARNING


def test_preflight_opaque_rgb_is_not_flagged(tmp_path, valid_file_item, default_settings):
    from PIL import Image

    valid_file_item.format = FileFormat.PDF
    valid_file_item.path = _pdf_with_image(
        tmp_path, Image.new("RGB", (80, 80), (0, 120, 255)), "rgb.pdf"
    )

    item = PreflightEngine().run_preflight(valid_file_item, default_settings)

    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.TRANSPARENCY_DETECTED not in types


def test_preflight_cmyk_file_is_not_flagged_transparent(
    tmp_path, valid_file_item, default_settings
):
    """The regression that mattered most: `colorspace == 4` means four inks,
    i.e. CMYK — the normal production file — never transparency."""
    from PIL import Image

    valid_file_item.format = FileFormat.PDF
    valid_file_item.path = _pdf_with_image(
        tmp_path, Image.new("CMYK", (80, 80), (0, 0, 0, 255)), "cmyk.pdf"
    )

    item = PreflightEngine().run_preflight(valid_file_item, default_settings)

    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.TRANSPARENCY_DETECTED not in types, (
        "un fichier CMJN conforme ne doit jamais être signalé transparent"
    )


@patch("src.core.engines.preflight_engine.fitz.open")
def test_preflight_pdf_corrupted(mock_fitz_open, valid_file_item, default_settings):
    valid_file_item.format = FileFormat.PDF
    
    mock_fitz_open.side_effect = fitz.FileDataError("File corrupted")
    
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)
    

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.CORRUPTED


@patch("src.core.engines.preflight_engine.PreflightEngine._check_resolution")
def test_preflight_generic_exception(mock_check_res, valid_file_item, default_settings):
    mock_check_res.side_effect = Exception("Unknown crash")
    
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)
    
    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.CORRUPTED
    assert "Unknown crash" in item.preflight_errors[0].message


# --------------------------------------------------------------------------- #
#  Embedded fonts — the discriminating field is `ext` (index 1), not `type`.
#  A tuple reads (xref, ext, type, basefont, name, encoding, referencer):
#    NOT embedded  (5, 'n/a', 'Type1', 'Helvetica', ...)
#    embedded      (5, 'ttf', 'Type0', 'Arial',     ...)
#  Testing index 2 would compare 'Type1'/'Type0' to 'n/a' and never fire.
# --------------------------------------------------------------------------- #

def _pdf_with_text(tmp_path, name, fontfile=None):
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    if fontfile:
        page.insert_text((30, 100), "Police embarquee", fontname="F0",
                         fontfile=fontfile, fontsize=14)
    else:
        page.insert_text((30, 100), "Police base-14", fontname="helv", fontsize=14)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def test_preflight_flags_a_non_embedded_font(tmp_path, valid_file_item, default_settings):
    """A base-14 font is only referenced: the RIP will substitute it."""
    valid_file_item.format = FileFormat.PDF
    valid_file_item.path = _pdf_with_text(tmp_path, "base14.pdf")

    item = PreflightEngine().run_preflight(valid_file_item, default_settings)

    errors = [e for e in item.preflight_errors
              if e.type == PreflightErrorType.FONTS_NOT_EMBEDDED]
    assert errors, "une police non embarquée doit être signalée"
    assert "Helvetica" in errors[0].message, "le nom de la police doit être cité"
    assert item.preflight_status == PreflightStatus.WARNING


@pytest.mark.skipif(
    not Path("C:/Windows/Fonts/arial.ttf").is_file(),
    reason="aucune police TTF système pour construire le cas embarqué",
)
def test_preflight_accepts_an_embedded_font(tmp_path, valid_file_item, default_settings):
    valid_file_item.format = FileFormat.PDF
    valid_file_item.path = _pdf_with_text(
        tmp_path, "embedded.pdf", fontfile="C:/Windows/Fonts/arial.ttf"
    )

    item = PreflightEngine().run_preflight(valid_file_item, default_settings)

    types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.FONTS_NOT_EMBEDDED not in types


def test_font_embedding_uses_ext_not_type():
    """Guards the exact confusion that made the first fix proposal inert."""
    not_embedded = (5, "n/a", "Type1", "Helvetica", "helv", "WinAnsiEncoding", 0)
    embedded = (5, "ttf", "Type0", "Arial Regular", "F0", "Identity-H", 0)

    assert PreflightEngine._font_is_embedded(embedded) is True
    assert PreflightEngine._font_is_embedded(not_embedded) is False
    # If the check ever regresses to index 2, both tuples read the same.
    assert not_embedded[2] != "n/a" and embedded[2] != "n/a"


def test_image_alpha_uses_smask_not_colorspace():
    """CMYK (colorspace 4) must never read as transparency."""
    assert PreflightEngine._image_has_alpha({"smask": 6, "colorspace": 3}) is True
    assert PreflightEngine._image_has_alpha({"smask": 0, "colorspace": 3}) is False
    assert PreflightEngine._image_has_alpha({"smask": 0, "colorspace": 4}) is False

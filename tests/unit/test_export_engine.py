from pathlib import Path
from unittest.mock import MagicMock, patch
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
        assert pdf.docinfo["/GTS_PDFXVersion"] == "PDF/X-1a:2001"


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


# --------------------------------------------------------------------------- #
#  Colour management of raster exports                                         #
#  Regression: print software refused the TIFFs because they carried no colour #
#  space tag, and the naive CMYK conversion put ~295 % ink on blacks.          #
# --------------------------------------------------------------------------- #

def _a_cmyk_profile():
    from src.core.engines.icc_engine import discover_profiles

    found = discover_profiles(cmyk_only=True)
    return found[0].path if found else None


_CMYK_PROFILE = _a_cmyk_profile()
needs_profile = pytest.mark.skipif(
    _CMYK_PROFILE is None, reason="aucun profil ICC CMJN installé sur la machine"
)


@pytest.fixture
def black_pdf_path(tmp_path):
    """Half solid black, half white — the case that reveals the ink overload."""
    pdf_path = tmp_path / "black.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=100)
    page.draw_rect(fitz.Rect(0, 0, 100, 100), color=(0, 0, 0), fill=(0, 0, 0))
    page.draw_rect(fitz.Rect(100, 0, 200, 100), color=(1, 1, 1), fill=(1, 1, 1))
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@needs_profile
def test_tiff_export_is_tagged_with_a_colour_space(export_engine, base_pdf_path, output_dir):
    """An untagged CMYK TIFF has no declared colour space and gets rejected."""
    settings = JobSettings(export_format="TIFF", export_dpi=150,
                           icc_profile_path=str(_CMYK_PROFILE))
    result = export_engine.export_sheet(uuid4(), Sheet(job_id=uuid4(), sheet_number=1),
                                        base_pdf_path, settings, output_dir)

    with Image.open(result) as img:
        assert img.info.get("icc_profile"), "le TIFF doit embarquer son profil ICC"
        assert 34675 in img.tag_v2, "le tag ICCProfile (34675) doit être présent"


@needs_profile
def test_black_stays_a_clean_k_instead_of_flooding_ink(
    export_engine, black_pdf_path, output_dir
):
    """Naive conversion gave C184 M172 J171 N225 (~295 % ink); a RIP refuses that.
    Through the profile it must come out as essentially pure K."""
    settings = JobSettings(export_format="TIFF", export_dpi=150,
                           icc_profile_path=str(_CMYK_PROFILE))
    result = export_engine.export_sheet(uuid4(), Sheet(job_id=uuid4(), sheet_number=1),
                                        black_pdf_path, settings, output_dir)

    with Image.open(result) as img:
        width, height = img.size
        c, m, y, k = img.getpixel((width // 4, height // 2))

    total_ink = (c + m + y + k) / 255 * 100
    assert total_ink < 260, f"encrage total {total_ink:.0f} % — le RIP refusera"
    assert k > 200, f"le noir doit porter sur le canal N (N={k})"


@needs_profile
def test_raster_to_raster_conversion_is_also_tagged(export_engine, base_pdf_path,
                                                    output_dir, tmp_path):
    """The convert_existing path must not silently drop the colour space either."""
    tiff_settings = JobSettings(export_format="TIFF", export_dpi=150,
                                icc_profile_path=str(_CMYK_PROFILE))
    sheet = Sheet(job_id=uuid4(), sheet_number=1, width_mm=70.0, height_mm=70.0)
    source = export_engine.export_sheet(uuid4(), sheet, base_pdf_path, tiff_settings,
                                        output_dir)

    dest = tmp_path / "converted"
    dest.mkdir()
    jpeg_settings = JobSettings(export_format="JPEG", export_dpi=150,
                                icc_profile_path=str(_CMYK_PROFILE))
    result = export_engine.convert_existing(uuid4(), sheet, source, jpeg_settings, dest)

    with Image.open(result) as img:
        assert img.info.get("icc_profile"), "la conversion doit conserver le profil"


def test_export_without_profile_still_produces_a_readable_tiff(
    export_engine, base_pdf_path, output_dir, monkeypatch
):
    """No profile anywhere on the machine must degrade, not crash."""
    monkeypatch.setattr(
        "src.core.engines.icc_engine.discover_profiles", lambda cmyk_only=True: []
    )
    settings = JobSettings(export_format="TIFF", export_dpi=150, icc_profile_path="")
    result = export_engine.export_sheet(uuid4(), Sheet(job_id=uuid4(), sheet_number=1),
                                        base_pdf_path, settings, output_dir)

    with Image.open(result) as img:
        assert img.format == "TIFF" and img.mode == "CMYK"


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
        assert pdf.docinfo["/GTS_PDFXVersion"] == "PDF/X-4"


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


def test_export_filename_uses_job_name(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=3)
    settings = JobSettings(export_format="TIFF")

    result_path = export_engine.export_sheet(
        job_id, sheet, base_pdf_path, settings, output_dir, job_name="Client Projet X"
    )

    assert result_path.name == "client_projet_x_planche_03.tiff"


def test_export_filename_falls_back_to_job_id(export_engine, base_pdf_path, output_dir):
    job_id = uuid4()
    sheet = Sheet(job_id=job_id, sheet_number=1)
    settings = JobSettings(export_format="TIFF")

    result_path = export_engine.export_sheet(job_id, sheet, base_pdf_path, settings, output_dir)

    assert result_path.name == f"{str(job_id)[:8]}_planche_01.tiff"


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



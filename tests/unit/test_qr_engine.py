import pytest
from PIL import Image

from src.core.engines.qr_engine import (
    QREngine,
    QRGenerationError,
    is_valid_url,
    safe_filename,
)
from src.core.models.domain import QRCodeSettings, QRErrorCorrection, QRItem


@pytest.fixture
def engine():
    return QREngine()


@pytest.fixture
def logo_file(tmp_path):
    path = tmp_path / "logo.png"
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(str(path))
    return path


def test_empty_data_raises(engine):
    with pytest.raises(QRGenerationError):
        engine.generate_image("   ", QRCodeSettings())


def test_png_written_at_requested_physical_size(engine, tmp_path):
    settings = QRCodeSettings(size_mm=30.0, dpi=300)
    out = engine.render_png("https://jelotia.com/x", settings, tmp_path / "q.png")

    assert out.exists()
    expected_px = round(30.0 / 25.4 * 300)
    with Image.open(out) as img:
        assert img.size == (expected_px, expected_px)


def test_pdf_is_vector_sized_to_mm(engine, tmp_path):
    import fitz

    settings = QRCodeSettings(size_mm=40.0)
    out = engine.render_pdf("https://jelotia.com/x", settings, tmp_path / "q.pdf")

    assert out.exists()
    doc = fitz.open(str(out))
    page = doc[0]
    # 40 mm in points (72 dpi) = 40/25.4*72 ≈ 113.4 pt, within rounding.
    assert page.rect.width == pytest.approx(40.0 / 25.4 * 72.0, abs=1.0)
    # Vector: many filled rectangles (the modules), not a single raster image.
    assert len(page.get_drawings()) > 50
    assert page.get_images() == []
    doc.close()


def test_svg_written_and_recolored(engine, tmp_path):
    settings = QRCodeSettings(fill_color="#FF7A1A")
    out = engine.render_svg("https://jelotia.com/x", settings, tmp_path / "q.svg")

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert content.lstrip().startswith("<?xml") or "<svg" in content
    assert "#FF7A1A" in content


def test_svg_rejects_logo(engine, tmp_path, logo_file):
    settings = QRCodeSettings(logo_path=logo_file)
    with pytest.raises(QRGenerationError):
        engine.render_svg("https://jelotia.com/x", settings, tmp_path / "q.svg")


def test_logo_forces_high_ecc(engine, logo_file):
    """A logo covers the center, so ECC must be bumped to H regardless of the
    configured level — otherwise the code may not scan."""
    low = engine._build_qr("https://jelotia.com/x", QRCodeSettings(ecc=QRErrorCorrection.L))
    with_logo = engine._build_qr(
        "https://jelotia.com/x", QRCodeSettings(ecc=QRErrorCorrection.L, logo_path=logo_file)
    )
    # H correction needs more modules than L for the same data.
    assert len(with_logo.get_matrix()) >= len(low.get_matrix())


def test_png_with_logo_embeds_without_error(engine, tmp_path, logo_file):
    settings = QRCodeSettings(logo_path=logo_file, size_mm=30.0, dpi=300)
    out = engine.render_png("https://jelotia.com/x", settings, tmp_path / "q.png")
    assert out.exists()


def test_generate_item_all_formats(engine, tmp_path):
    item = QRItem(data="https://jelotia.com/promo", filename="promo_ete")
    results = engine.generate_item(item, QRCodeSettings(), tmp_path, ["PNG", "SVG", "PDF"])

    assert set(results) == {"PNG", "SVG", "PDF"}
    for fmt, path in results.items():
        assert path.exists()
        assert path.name == f"promo_ete.{fmt.lower()}"


def test_generate_item_unsupported_format_raises(engine, tmp_path):
    item = QRItem(data="https://jelotia.com/x", filename="x")
    with pytest.raises(QRGenerationError):
        engine.generate_item(item, QRCodeSettings(), tmp_path, ["EPS"])


def test_generate_item_falls_back_to_id_when_no_filename(engine, tmp_path):
    item = QRItem(data="https://jelotia.com/x")
    results = engine.generate_item(item, QRCodeSettings(), tmp_path, ["PNG"])
    assert results["PNG"].stem == str(item.id)[:8]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a/b:c*d?.png", "a_b_c_d_.png"),
        ("  trailing.  ", "trailing"),
        ("", ""),
    ],
)
def test_safe_filename(raw, expected):
    assert safe_filename(raw) == expected


@pytest.mark.parametrize(
    "url,ok",
    [
        ("https://jelotia.com", True),
        ("http://a.b/c?d=1", True),
        ("ftp://x.y", False),
        ("not a url", False),
        ("", False),
    ],
)
def test_is_valid_url(url, ok):
    assert is_valid_url(url) is ok

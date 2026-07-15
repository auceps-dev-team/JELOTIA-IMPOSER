import fitz
import pytest
from PIL import Image

from src.core.engines.bleed_engine import (
    BleedError,
    add_bleed,
    available_bleed_mm,
    ensure_bleed,
)

_MM_TO_PT = 72.0 / 25.4


def _pixel_at_mm(pix, x_mm, y_mm, zoom):
    k = _MM_TO_PT * zoom
    return pix.pixel(int(x_mm * k), int(y_mm * k))


@pytest.fixture
def artwork(tmp_path):
    """50×30 mm artwork: red left edge, blue right edge, green top edge,
    white middle — so each bleed band can be checked against its own edge."""
    path = tmp_path / "art.pdf"
    doc = fitz.open()
    w, h = 50 * _MM_TO_PT, 30 * _MM_TO_PT
    page = doc.new_page(width=w, height=h)
    page.draw_rect(fitz.Rect(0, 0, 3 * _MM_TO_PT, h), color=None, fill=(1, 0, 0))
    page.draw_rect(fitz.Rect(w - 3 * _MM_TO_PT, 0, w, h), color=None, fill=(0, 0, 1))
    page.draw_rect(fitz.Rect(0, 0, w, 3 * _MM_TO_PT), color=None, fill=(0, 0.6, 0))
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------- #
#  PDF                                                                         #
# --------------------------------------------------------------------------- #

def test_add_bleed_grows_the_page_by_two_bleeds(artwork, tmp_path):
    out = add_bleed(artwork, 3.0, tmp_path / "out.pdf")
    doc = fitz.open(str(out))
    page = doc[0]
    assert page.rect.width == pytest.approx((50 + 6) * _MM_TO_PT, abs=0.5)
    assert page.rect.height == pytest.approx((30 + 6) * _MM_TO_PT, abs=0.5)
    doc.close()


def test_bleed_bands_extend_the_edge_colours(artwork, tmp_path):
    """Le fond perdu doit prolonger la couleur du bord — pas laisser du blanc,
    sinon la coupe laisse un liseré."""
    out = add_bleed(artwork, 3.0, tmp_path / "out.pdf")
    doc = fitz.open(str(out))
    zoom = 4.0
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    doc.close()

    # Repère : l'œuvre occupe [3, 53] × [3, 33] mm dans la page étendue.
    r, g, b = _pixel_at_mm(pix, 1.5, 18, zoom)          # bande gauche
    assert r > 200 and b < 60, f"fond perdu gauche doit être rouge, obtenu ({r},{g},{b})"
    r, g, b = _pixel_at_mm(pix, 54.5, 18, zoom)         # bande droite
    assert b > 200 and r < 60, f"fond perdu droit doit être bleu, obtenu ({r},{g},{b})"
    r, g, b = _pixel_at_mm(pix, 28, 1.5, zoom)          # bande haute
    assert g > 100 and r < 100, f"fond perdu haut doit être vert, obtenu ({r},{g},{b})"
    # Coin haut-gauche : prolonge le coin rouge/vert, jamais blanc.
    r, g, b = _pixel_at_mm(pix, 1.5, 1.5, zoom)
    assert not (r > 200 and g > 200 and b > 200), "le coin ne doit pas rester blanc"


def test_artwork_is_preserved_and_still_vector(artwork, tmp_path):
    out = add_bleed(artwork, 3.0, tmp_path / "out.pdf")
    doc = fitz.open(str(out))
    page = doc[0]
    zoom = 4.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    # Le centre de l'œuvre reste blanc (non déformé par les bandes).
    assert min(_pixel_at_mm(pix, 28, 18, zoom)) > 200
    assert page.get_images() == [], "le fond perdu ne doit pas rasteriser l'œuvre"
    doc.close()


def test_existing_bleed_is_detected_and_reused(tmp_path):
    """Un PDF portant déjà un vrai fond perdu ne doit pas être réinventé."""
    path = tmp_path / "with_bleed.pdf"
    doc = fitz.open()
    page = doc.new_page(width=56 * _MM_TO_PT, height=36 * _MM_TO_PT)
    page.set_trimbox(fitz.Rect(3 * _MM_TO_PT, 3 * _MM_TO_PT, 53 * _MM_TO_PT, 33 * _MM_TO_PT))
    doc.save(str(path))
    doc.close()

    assert available_bleed_mm(path) == pytest.approx(3.0, abs=0.1)

    result, applied = ensure_bleed(path, 3.0, tmp_path / "work")
    assert result == path, "le fichier d'origine est conservé tel quel"
    assert applied == 0.0


def test_ensure_bleed_generates_when_missing(artwork, tmp_path):
    assert available_bleed_mm(artwork) == 0.0
    result, applied = ensure_bleed(artwork, 3.0, tmp_path / "work")
    assert result != artwork and result.exists()
    assert applied == 3.0
    assert result.parent == tmp_path / "work"


def test_ensure_bleed_noop_when_disabled(artwork, tmp_path):
    result, applied = ensure_bleed(artwork, 0.0, tmp_path / "work")
    assert result == artwork and applied == 0.0


def test_add_bleed_rejects_bad_input(tmp_path, artwork):
    with pytest.raises(BleedError):
        add_bleed(artwork, 0.0, tmp_path / "x.pdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"pas un pdf")
    with pytest.raises(BleedError):
        add_bleed(broken, 3.0, tmp_path / "y.pdf")


# --------------------------------------------------------------------------- #
#  Raster                                                                      #
# --------------------------------------------------------------------------- #

def test_raster_bleed_mirrors_edges(tmp_path):
    src = tmp_path / "photo.png"
    image = Image.new("RGB", (100, 60), "white")
    for y in range(60):
        for x in range(5):
            image.putpixel((x, y), (255, 0, 0))       # bord gauche rouge
            image.putpixel((99 - x, y), (0, 0, 255))  # bord droit bleu
    image.save(str(src), dpi=(254, 254))  # 254 dpi -> 10 px/mm

    out = add_bleed(src, 1.0, tmp_path / "out.png")
    with Image.open(out) as result:
        assert result.size == (120, 80), "10 px de fond perdu de chaque côté"
        assert result.getpixel((3, 40))[0] > 200, "bande gauche miroir = rouge"
        assert result.getpixel((116, 40))[2] > 200, "bande droite miroir = bleue"
        assert min(result.getpixel((60, 40))) > 200, "l'image reste au centre"


def test_raster_bleed_rejects_unreadable(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"pas une image")
    with pytest.raises(BleedError):
        add_bleed(bad, 2.0, tmp_path / "out.png")


# --------------------------------------------------------------------------- #
#  Integration: pipeline + trim-aware marks                                    #
# --------------------------------------------------------------------------- #

def test_pipeline_applies_bleed_and_grows_the_item(artwork, tmp_path, monkeypatch):
    import uuid

    from src.core.models.domain import JobSettings
    from src.core.processors.job_processor import process_job_files
    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "proc")

    settings = JobSettings(add_bleed_mm=3.0, force_cmyk=False)
    items = process_job_files(uuid.uuid4(), [artwork], settings)

    assert len(items) == 1
    item = items[0]
    assert item.bleed_mm == pytest.approx(3.0)
    # 50×30 mm d'œuvre -> 56×36 mm imprimés (fond perdu compris).
    assert item.width_mm == pytest.approx(56.0, abs=0.5)
    assert item.height_mm == pytest.approx(36.0, abs=0.5)
    assert item.path != artwork, "l'item pointe sur la copie avec fond perdu"


def test_pipeline_without_bleed_setting_changes_nothing(artwork, tmp_path, monkeypatch):
    import uuid

    from src.core.models.domain import JobSettings
    from src.core.processors.job_processor import process_job_files
    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "proc")

    items = process_job_files(uuid.uuid4(), [artwork], JobSettings(force_cmyk=False))
    assert items[0].bleed_mm == 0.0
    assert items[0].width_mm == pytest.approx(50.0, abs=0.5)


def test_cut_marks_target_the_trim_not_the_bleed(tmp_path):
    """LE point prépresse : couper au bord du fond perdu laisserait l'œuvre
    étendue sur le produit fini — les traits doivent viser le format fini."""
    import uuid

    from src.core.engines.layout_engine import LayoutEngine
    from src.core.models.domain import JobSettings, PlacedItem, Sheet

    item = PlacedItem(
        file_item_id=uuid.uuid4(), source_path="absent.pdf",
        x_mm=20, y_mm=20, width_mm=56, height_mm=36, bleed_mm=3.0,
    )
    assert item.trim_rect_mm() == (23.0, 23.0, 50.0, 30.0)

    sheet = Sheet(job_id=uuid.uuid4(), sheet_number=1, width_mm=120, height_mm=100,
                  items=[item])
    settings = JobSettings(draw_cutlines=True, add_crop_marks=False,
                           generate_thumbnail=False, cut_contour_spot=True)
    out = LayoutEngine().generate_sheet_pdf(uuid.uuid4(), sheet, settings, tmp_path)

    doc = fitz.open(str(out))
    page = doc[0]
    zoom = 4.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    doc.close()

    def is_marked(x_mm, y_from_bottom_mm):
        # ReportLab dessine depuis le BAS, fitz rend depuis le HAUT : convertir,
        # sinon on échantillonne hors de la pose.
        r, g, b = _pixel_at_mm(pix, x_mm, sheet.height_mm - y_from_bottom_mm, zoom)
        return min(r, g, b) < 220  # une ligne (rouge ou magenta) a été tracée

    # La pose imprimée couvre x 20..76 ; le format fini x 23..73, y 23..53.
    # Le trait de coupe longe le format fini (x = 23 mm)...
    assert is_marked(23.0, 40.0), "trait de coupe attendu au format fini"
    # ...et PAS le bord du fond perdu (x = 20 mm).
    assert not is_marked(20.0, 40.0), "aucun trait ne doit longer le fond perdu"

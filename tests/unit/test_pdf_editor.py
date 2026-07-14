import fitz
import pytest
from PIL import Image

from src.core.engines.pdf_editor import PdfEditError, PdfEditSession


def _make_pdf(path, labels, width=200, height=300):
    """A PDF with one page per label, each page carrying its label as text."""
    doc = fitz.open()
    for label in labels:
        page = doc.new_page(width=width, height=height)
        page.insert_text(fitz.Point(30, 50), label, fontsize=20)
    doc.save(str(path))
    doc.close()
    return path


def _page_texts(path):
    doc = fitz.open(str(path))
    texts = [doc[i].get_text().strip() for i in range(doc.page_count)]
    doc.close()
    return texts


@pytest.fixture
def sample_pdf(tmp_path):
    return _make_pdf(tmp_path / "sample.pdf", ["PAGE A", "PAGE B", "PAGE C"])


@pytest.fixture
def session(sample_pdf):
    s = PdfEditSession()
    s.open(sample_pdf)
    yield s
    s.close()


def test_open_and_page_count(session):
    assert session.is_open
    assert session.page_count == 3
    assert session.modified is False


def test_open_rejects_garbage(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"pas un pdf")
    with pytest.raises(PdfEditError):
        PdfEditSession().open(bad)


def test_rotate_page_persists(session, tmp_path):
    session.rotate_page(0, 90)
    out = session.save_as(tmp_path / "out.pdf")

    doc = fitz.open(str(out))
    assert doc[0].rotation == 90
    assert doc[1].rotation == 0
    doc.close()


def test_delete_pages(session, tmp_path):
    session.delete_pages([1])
    assert session.page_count == 2
    out = session.save_as(tmp_path / "out.pdf")
    assert _page_texts(out) == ["PAGE A", "PAGE C"]


def test_delete_all_pages_refused(session):
    with pytest.raises(PdfEditError):
        session.delete_pages([0, 1, 2])


def test_move_page_right_and_left(session, tmp_path):
    session.move_page(0, 2)  # A after C -> B, C, A
    out = session.save_as(tmp_path / "out1.pdf")
    assert _page_texts(out) == ["PAGE B", "PAGE C", "PAGE A"]

    session.move_page(2, 0)  # back to front -> A, B, C
    out = session.save_as(tmp_path / "out2.pdf")
    assert _page_texts(out) == ["PAGE A", "PAGE B", "PAGE C"]


def test_duplicate_page(session, tmp_path):
    session.duplicate_page(0)
    assert session.page_count == 4
    out = session.save_as(tmp_path / "out.pdf")
    assert _page_texts(out) == ["PAGE A", "PAGE A", "PAGE B", "PAGE C"]


def test_merge_pdf(session, tmp_path):
    other = _make_pdf(tmp_path / "other.pdf", ["PAGE D"])
    added = session.merge_pdf(other)
    assert added == 1
    assert session.page_count == 4
    out = session.save_as(tmp_path / "out.pdf")
    assert _page_texts(out)[-1] == "PAGE D"


def test_extract_pages(session, tmp_path):
    out = session.extract_pages([2, 0], tmp_path / "extrait.pdf")
    assert _page_texts(out) == ["PAGE A", "PAGE C"]
    assert session.page_count == 3  # source untouched


def test_add_text(session, tmp_path):
    session.add_text(1, x_mm=10, y_mm=10, text="BON À TIRER", font_size_pt=14, bold=True)
    out = session.save_as(tmp_path / "out.pdf")
    texts = _page_texts(out)
    assert "BON À TIRER" in texts[1]
    assert "BON À TIRER" not in texts[0]


def test_add_image(session, tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGB", (100, 50), "#FF7A1A").save(str(logo))

    session.add_image(0, x_mm=5, y_mm=5, width_mm=20, image_path=logo)
    out = session.save_as(tmp_path / "out.pdf")

    doc = fitz.open(str(out))
    assert len(doc[0].get_images()) == 1
    assert doc[1].get_images() == []
    doc.close()


def test_duplicate_single_page_document(tmp_path):
    """Regression (field report): duplicating always failed on a one-page
    file — fullcopy_page's `to` must be an existing page or -1."""
    pdf = _make_pdf(tmp_path / "one.pdf", ["SEULE"])
    s = PdfEditSession()
    s.open(pdf)
    s.duplicate_page(0)
    assert s.page_count == 2
    out = s.save_as(tmp_path / "out.pdf")
    assert _page_texts(out) == ["SEULE", "SEULE"]
    s.close()


def test_duplicate_last_page(session, tmp_path):
    session.duplicate_page(2)
    out = session.save_as(tmp_path / "out.pdf")
    assert _page_texts(out) == ["PAGE A", "PAGE B", "PAGE C", "PAGE C"]


def test_insert_blank_page(session, tmp_path):
    session.insert_blank_page(0)
    assert session.page_count == 4
    out = session.save_as(tmp_path / "out.pdf")
    assert _page_texts(out) == ["PAGE A", "", "PAGE B", "PAGE C"]

    doc = fitz.open(str(out))
    assert doc[1].rect.width == pytest.approx(200, abs=0.5)
    assert doc[1].rect.height == pytest.approx(300, abs=0.5)
    doc.close()


def test_add_text_on_rotated_page(session, tmp_path):
    """Stamps use displayed coordinates; on a rotated page they must be
    derotated so the text lands where the operator clicked."""
    session.rotate_page(0, 90)
    session.add_text(0, x_mm=10, y_mm=10, text="TAMPON PIVOTÉ")
    out = session.save_as(tmp_path / "out.pdf")
    assert "TAMPON PIVOTÉ" in _page_texts(out)[0]


def test_page_size_mm_follows_rotation(session):
    """page.rect in fitz already reflects rotation — the displayed size must
    swap after a 90° turn (this drives the preview's mm mapping)."""
    w0, h0 = session.page_size_mm(0)
    session.rotate_page(0, 90)
    w1, h1 = session.page_size_mm(0)
    assert (w1, h1) == pytest.approx((h0, w0))


# --------------------------------------------------------------------------- #
#  Text search & replace                                                       #
# --------------------------------------------------------------------------- #

@pytest.fixture
def price_pdf(tmp_path):
    path = tmp_path / "price.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text(fitz.Point(30, 50), "Prix : 1000 FCFA", fontsize=14)
    page.insert_text(fitz.Point(30, 90), "Livraison gratuite", fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_find_text_returns_occurrences(price_pdf):
    s = PdfEditSession()
    s.open(price_pdf)
    rects = s.find_text(0, "1000 FCFA")
    assert len(rects) == 1
    assert rects[0].y1 <= 60
    assert s.find_text(0, "INTROUVABLE") == []
    assert s.find_text(0, "   ") == []
    s.close()


def test_text_style_detection(price_pdf):
    s = PdfEditSession()
    s.open(price_pdf)
    rect = s.find_text(0, "1000 FCFA")[0]
    style = s.text_style_at(0, rect)
    assert style["font_size_pt"] == pytest.approx(14.0, abs=0.5)
    assert style["color"] == "#000000"
    s.close()


def test_replace_text_swaps_content(price_pdf, tmp_path):
    s = PdfEditSession()
    s.open(price_pdf)
    rects = s.find_text(0, "1000 FCFA")
    s.replace_text(0, rects, "1500 FCFA", font_size_pt=14.0)

    out = s.save_as(tmp_path / "out.pdf")
    text = _page_texts(out)[0]
    assert "1500 FCFA" in text
    assert "1000 FCFA" not in text
    assert "Livraison gratuite" in text, "le reste de la page doit être intact"

    assert s.can_undo
    s.undo()
    assert "1000 FCFA" in s.doc[0].get_text()
    s.close()


def test_replace_text_with_empty_string_erases(price_pdf, tmp_path):
    s = PdfEditSession()
    s.open(price_pdf)
    rects = s.find_text(0, "Livraison gratuite")
    s.replace_text(0, rects, "")
    out = s.save_as(tmp_path / "out.pdf")
    assert "Livraison" not in _page_texts(out)[0]
    s.close()


def test_preview_does_not_touch_session(price_pdf):
    s = PdfEditSession()
    s.open(price_pdf)
    rects = s.find_text(0, "1000 FCFA")

    pix = s.preview_replace_text(0, rects, "9999 FCFA", font_size_pt=14.0)

    assert pix.width > 0
    assert "1000 FCFA" in s.doc[0].get_text(), "l'aperçu ne doit pas modifier la session"
    assert s.modified is False
    assert not s.can_undo
    s.close()


def test_replace_text_protects_images(tmp_path):
    """Redaction must not eat an image near/overlapping the text area."""
    img = tmp_path / "logo.png"
    Image.new("RGB", (60, 60), "#FF0000").save(str(img))
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(50, 20, 110, 80), filename=str(img))
    page.insert_text(fitz.Point(50, 100), "ANCIEN", fontsize=12)
    doc.save(str(pdf))
    doc.close()

    s = PdfEditSession()
    s.open(pdf)
    rects = s.find_text(0, "ANCIEN")
    s.replace_text(0, rects, "NOUVEAU", font_size_pt=12.0)
    assert len(s.list_images(0)) == 1, "l'image doit survivre à la rédaction"
    assert "NOUVEAU" in s.doc[0].get_text()
    s.close()


def test_add_text_with_covering_background(tmp_path):
    """On a colored page, a covering-background stamp must mask what's below
    (the scanned-page retouching technique)."""
    pdf = tmp_path / "yellow.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_rect(page.rect, color=None, fill=(1.0, 0.8, 0.0))  # yellow page
    doc.save(str(pdf))
    doc.close()

    s = PdfEditSession()
    s.open(pdf)
    s.add_text(0, x_mm=20, y_mm=20, text="1333207", font_size_pt=12,
               bg_color="#FFFFFF")

    pix = s.render_page(0, target_width_px=400)
    zoom = 400 / 200
    k = 72 / 25.4
    # Sample inside the covering rect but away from the glyphs' ink.
    x_px = int((20 * k + 2) * zoom)
    y_px = int((20 * k + 1) * zoom)
    r, g, b = pix.pixel(x_px, y_px)
    assert min(r, g, b) > 220, f"le fond couvrant doit être blanc, obtenu ({r},{g},{b})"
    assert "1333207" in s.doc[0].get_text()
    s.close()


def test_page_text_diagnosis(price_pdf, tmp_path):
    s = PdfEditSession()
    s.open(price_pdf)
    assert s.page_text_diagnosis(0) == "has_text"
    s.close()

    # Image-only page (a scan): no text, one raster image.
    img = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "#CCCCCC").save(str(img))
    scanned = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(page.rect, filename=str(img))
    doc.save(str(scanned))
    doc.close()
    s.open(scanned)
    assert s.page_text_diagnosis(0) == "scanned_image"
    s.close()

    # Vector-only page (outlined text case).
    vector = tmp_path / "vector.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.draw_circle(fitz.Point(100, 100), 40, color=(0, 0, 0), width=2)
    doc.save(str(vector))
    doc.close()
    s.open(vector)
    assert s.page_text_diagnosis(0) == "vector_only"
    s.close()

    blank = _make_pdf(tmp_path / "blank.pdf", [""])
    s.open(blank)
    assert s.page_text_diagnosis(0) == "empty"
    s.close()


# --------------------------------------------------------------------------- #
#  Images: list / replace / delete by xref                                     #
# --------------------------------------------------------------------------- #

def _color_png(tmp_path, name, color):
    path = tmp_path / name
    Image.new("RGB", (80, 60), color).save(str(path))
    return path


@pytest.fixture
def pdf_with_image(tmp_path):
    """One page with a red image placed at a known rectangle."""
    red = _color_png(tmp_path, "red.png", "#FF0000")
    path = tmp_path / "with_image.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=300)
    page.insert_text(fitz.Point(20, 30), "TITRE")
    page.insert_image(fitz.Rect(50, 100, 150, 175), filename=str(red))
    doc.save(str(path))
    doc.close()
    return path


def _center_pixel(session, index, rect):
    """RGB of the rendered pixel at the center of `rect` (page pt space)."""
    page_w = session.doc[index].rect.width
    pix = session.render_page(index, target_width_px=400)
    zoom = pix.width / page_w
    x, y = int((rect.x0 + rect.x1) / 2 * zoom), int((rect.y0 + rect.y1) / 2 * zoom)
    return pix.pixel(x, y)


def test_list_images(pdf_with_image):
    s = PdfEditSession()
    s.open(pdf_with_image)
    images = s.list_images(0)
    assert len(images) == 1
    entry = images[0]
    assert entry["xref"] > 0
    assert entry["rect"].x0 == pytest.approx(50, abs=1)
    assert entry["rect"].y1 == pytest.approx(175, abs=1)
    assert (entry["width"], entry["height"]) == (80, 60)
    assert s.image_preview(entry["xref"]) is not None
    s.close()


def test_replace_image_keeps_frame(pdf_with_image, tmp_path):
    blue = _color_png(tmp_path, "blue.png", "#0000FF")
    s = PdfEditSession()
    s.open(pdf_with_image)
    entry = s.list_images(0)[0]
    old_rect = entry["rect"]

    s.replace_image(0, entry["xref"], blue)

    r, g, b = _center_pixel(s, 0, old_rect)
    assert b > 200 and r < 60, f"le centre doit être bleu, obtenu ({r},{g},{b})"
    new_entry = s.list_images(0)[0]
    assert new_entry["rect"] == old_rect, "le cadre doit rester identique"

    out = s.save_as(tmp_path / "out.pdf")
    assert "TITRE" in _page_texts(out)[0]  # le reste du contenu est intact
    s.close()


def test_replace_image_rejects_bad_file(pdf_with_image, tmp_path):
    bad = tmp_path / "pas_une_image.png"
    bad.write_bytes(b"garbage")
    s = PdfEditSession()
    s.open(pdf_with_image)
    entry = s.list_images(0)[0]
    with pytest.raises(PdfEditError):
        s.replace_image(0, entry["xref"], bad)
    assert s.modified is False, "un fichier invalide ne doit rien modifier"
    s.close()


def test_delete_image_blanks_the_spot(pdf_with_image):
    s = PdfEditSession()
    s.open(pdf_with_image)
    entry = s.list_images(0)[0]

    s.delete_image(0, entry["xref"])

    r, g, b = _center_pixel(s, 0, entry["rect"])
    assert min(r, g, b) > 200, f"l'emplacement doit être blanc, obtenu ({r},{g},{b})"
    assert s.can_undo
    s.undo()
    r, g, b = _center_pixel(s, 0, entry["rect"])
    assert r > 200 and b < 60, "l'annulation doit restaurer l'image rouge"
    s.close()


def test_undo_restores_previous_state(session):
    session.delete_pages([0])
    assert session.page_count == 2
    assert session.can_undo

    assert session.undo() is True
    assert session.page_count == 3

    assert session.undo() is False  # stack exhausted


def test_render_page_and_size(session):
    pix = session.render_page(0, target_width_px=400)
    assert pix.width == pytest.approx(400, abs=2)

    w_mm, h_mm = session.page_size_mm(0)
    assert w_mm == pytest.approx(200 / 72 * 25.4, abs=0.1)
    assert h_mm == pytest.approx(300 / 72 * 25.4, abs=0.1)


def test_operations_require_open_document():
    s = PdfEditSession()
    with pytest.raises(PdfEditError):
        s.rotate_page(0, 90)

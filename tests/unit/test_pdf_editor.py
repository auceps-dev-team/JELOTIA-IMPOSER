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

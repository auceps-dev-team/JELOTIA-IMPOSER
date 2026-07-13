import fitz
import pytest

from src.core.engines.qr_batch import ColumnMapping, build_plan, generate_batch
from src.core.engines.qr_engine import QREngine
from src.core.engines.template_composer import (
    STANDARD_FORMATS,
    TemplateComposer,
    TemplateStore,
    substitute_placeholders,
)
from src.core.models.domain import (
    CardTemplate,
    QRCodeSettings,
    TemplateQRZone,
    TemplateTextZone,
)

_MM_TO_PT = 72.0 / 25.4


@pytest.fixture
def composer():
    return TemplateComposer()


@pytest.fixture
def card():
    return CardTemplate(
        name="Carte test",
        width_mm=85.0,
        height_mm=55.0,
        qr_zone=TemplateQRZone(x_mm=60.0, y_mm=5.0, size_mm=20.0),
        texts=[
            TemplateTextZone(text="JELOTIA SARL", x_mm=5.0, y_mm=5.0, font_size_pt=12.0),
            TemplateTextZone(text="Client : {Nom}", x_mm=5.0, y_mm=20.0, font_size_pt=9.0),
        ],
    )


@pytest.fixture
def base_pdf(tmp_path):
    """A colored background artwork PDF."""
    path = tmp_path / "fond.pdf"
    doc = fitz.open()
    page = doc.new_page(width=85 * _MM_TO_PT, height=55 * _MM_TO_PT)
    page.draw_rect(page.rect, color=None, fill=(1.0, 0.5, 0.1))
    doc.save(str(path))
    doc.close()
    return path


def test_substitute_placeholders():
    row = {"Nom": "Dupont", "Ville": "Douala"}
    assert substitute_placeholders("Client {Nom} — {Ville}", row) == "Client Dupont — Douala"
    # Unknown placeholders stay visible instead of vanishing.
    assert substitute_placeholders("{Inconnu}", row) == "{Inconnu}"
    assert substitute_placeholders("Rien", None) == "Rien"


def test_compose_blank_template(composer, card, tmp_path):
    out = composer.compose(card, "https://jelotia.com/x", QRCodeSettings(), tmp_path / "c.pdf")

    assert out.exists()
    doc = fitz.open(str(out))
    page = doc[0]
    assert page.rect.width == pytest.approx(85 * _MM_TO_PT, abs=0.5)
    assert page.rect.height == pytest.approx(55 * _MM_TO_PT, abs=0.5)
    assert len(page.get_drawings()) > 50  # the vector QR modules
    text = page.get_text()
    assert "JELOTIA SARL" in text
    assert "Client : {Nom}" in text  # no row given -> placeholder stays
    doc.close()


def test_compose_substitutes_row_values(composer, card, tmp_path):
    out = composer.compose(
        card, "https://jelotia.com/x", QRCodeSettings(), tmp_path / "c.pdf",
        row={"Nom": "Dupont"},
    )
    doc = fitz.open(str(out))
    assert "Client : Dupont" in doc[0].get_text()
    doc.close()


def test_compose_with_background_pdf(composer, card, base_pdf, tmp_path):
    card.base_pdf = base_pdf
    out = composer.compose(card, "https://jelotia.com/x", QRCodeSettings(), tmp_path / "c.pdf")

    doc = fitz.open(str(out))
    assert doc.page_count == 1
    # The background xobject is embedded alongside the QR drawings.
    assert "JELOTIA SARL" in doc[0].get_text()
    doc.close()


def test_compose_missing_background_does_not_crash(composer, card, tmp_path):
    card.base_pdf = tmp_path / "disparu.pdf"
    out = composer.compose(card, "https://jelotia.com/x", QRCodeSettings(), tmp_path / "c.pdf")
    assert out.exists()


def test_store_roundtrip_and_base_copy(tmp_path, base_pdf, card):
    store = TemplateStore(tmp_path / "Templates")
    card.base_pdf = base_pdf
    saved = store.save(card)

    # Background copied inside the store, template repointed to the copy.
    assert saved.base_pdf.parent.resolve() == (tmp_path / "Templates").resolve()
    assert saved.base_pdf.exists()

    loaded = store.load(card.id)
    assert loaded.name == "Carte test"
    assert loaded.qr_zone.size_mm == 20.0
    assert len(loaded.texts) == 2

    assert [t.id for t in store.list()] == [card.id]
    store.delete(card.id)
    assert store.list() == []
    assert not saved.base_pdf.exists()


def test_standard_formats_present():
    labels = " ".join(STANDARD_FORMATS)
    for expected in ("A4", "A5", "A6", "A7", "Carte de visite", "Vignette"):
        assert expected in labels


def test_generate_batch_with_template_fuses_row_data(card, tmp_path):
    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "Dupont"},
        {"Lien": "https://jelotia.com/b", "Nom": "Martin"},
    ]
    plan = build_plan(rows, ColumnMapping(url_col="Lien"))
    result = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "out", ["PNG"],
        template=card,
    )

    assert result.succeeded == 2
    names = []
    for r in result.results:
        assert set(r.paths) == {"PDF"}  # template mode always outputs PDF
        doc = fitz.open(str(r.paths["PDF"]))
        names.append(doc[0].get_text())
        doc.close()
    assert "Client : Dupont" in names[0]
    assert "Client : Martin" in names[1]

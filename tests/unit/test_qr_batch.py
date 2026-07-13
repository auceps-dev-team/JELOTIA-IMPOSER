import csv
import zipfile

import openpyxl
import pytest

from src.core.engines.qr_batch import (
    ColumnMapping,
    build_plan,
    generate_batch,
    zip_outputs,
)
from src.core.engines.qr_engine import QREngine
from src.core.engines.qr_import import TableImportError, read_table
from src.core.models.domain import QRCodeSettings

# --------------------------------------------------------------------------- #
#  Import (Excel / CSV)                                                        #
# --------------------------------------------------------------------------- #

@pytest.fixture
def xlsx_file(tmp_path):
    path = tmp_path / "data.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Lien", "Nom", "Qte"])
    ws.append(["https://jelotia.com/a", "carte_a", 2])
    ws.append(["https://jelotia.com/b", "carte_b", 1])
    ws.append([None, None, None])  # blank row, must be skipped
    wb.save(str(path))
    return path


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "data.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Lien", "Nom", "Qte"])
        w.writerow(["https://jelotia.com/a", "carte_a", "2"])
        w.writerow(["https://jelotia.com/b", "carte_b", "1"])
    return path


def test_read_xlsx(xlsx_file):
    headers, rows = read_table(xlsx_file)
    assert headers == ["Lien", "Nom", "Qte"]
    assert len(rows) == 2
    assert rows[0]["Lien"] == "https://jelotia.com/a"
    assert rows[0]["Qte"] == "2"


def test_read_csv_semicolon_delimiter(csv_file):
    headers, rows = read_table(csv_file)
    assert headers == ["Lien", "Nom", "Qte"]
    assert len(rows) == 2
    assert rows[1]["Nom"] == "carte_b"


def test_read_table_rejects_unknown_extension(tmp_path):
    bad = tmp_path / "data.docx"
    bad.write_text("x")
    with pytest.raises(TableImportError):
        read_table(bad)


def test_headers_disambiguated(tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text("Lien,Lien,\nhttps://a,https://b,c\n", encoding="utf-8")
    headers, rows = read_table(path)
    assert headers[0] == "Lien"
    assert headers[1] == "Lien (2)"
    assert headers[2] == "Colonne 3"


# --------------------------------------------------------------------------- #
#  Plan building (mapping + dedup)                                            #
# --------------------------------------------------------------------------- #

def test_build_plan_maps_columns_and_quantity():
    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "carte_a", "Qte": "3"},
        {"Lien": "https://jelotia.com/b", "Nom": "carte_b", "Qte": ""},
    ]
    mapping = ColumnMapping(url_col="Lien", filename_col="Nom", quantity_col="Qte")
    plan = build_plan(rows, mapping)

    assert plan.total == 2
    assert plan.items[0].filename == "carte_a"
    assert plan.items[0].quantity == 3
    assert plan.items[1].quantity == 1  # empty qty -> default 1


def test_build_plan_skips_empty_urls():
    rows = [{"Lien": ""}, {"Lien": "  "}, {"Lien": "https://jelotia.com/a"}]
    plan = build_plan(rows, ColumnMapping(url_col="Lien"))
    assert plan.total == 1
    assert plan.empty_skipped == 2


def test_build_plan_rejects_duplicates_when_asked():
    rows = [
        {"Lien": "https://jelotia.com/a"},
        {"Lien": "https://jelotia.com/a"},
        {"Lien": "https://jelotia.com/b"},
    ]
    mapping = ColumnMapping(url_col="Lien")

    kept = build_plan(rows, mapping, allow_duplicates=True)
    assert kept.total == 3 and kept.duplicates_skipped == 0

    deduped = build_plan(rows, mapping, allow_duplicates=False)
    assert deduped.total == 2 and deduped.duplicates_skipped == 1


def test_build_plan_generates_fallback_filename():
    rows = [{"Lien": "https://jelotia.com/a"}]
    plan = build_plan(rows, ColumnMapping(url_col="Lien"))
    assert plan.items[0].filename == "qr_00001"


# --------------------------------------------------------------------------- #
#  Batch generation                                                           #
# --------------------------------------------------------------------------- #

def test_generate_batch_all_items_all_formats(tmp_path):
    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "carte_a"},
        {"Lien": "https://jelotia.com/b", "Nom": "carte_b"},
    ]
    plan = build_plan(rows, ColumnMapping(url_col="Lien", filename_col="Nom"))
    result = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "out", ["PNG", "PDF"]
    )

    assert result.succeeded == 2
    assert result.failed == 0
    for r in result.results:
        assert set(r.paths) == {"PNG", "PDF"}
        assert all(p.exists() for p in r.paths.values())


def test_generate_batch_reports_progress_and_deduplicates_names(tmp_path):
    # Two rows share a filename -> outputs must not overwrite each other.
    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "same"},
        {"Lien": "https://jelotia.com/b", "Nom": "same"},
    ]
    plan = build_plan(rows, ColumnMapping(url_col="Lien", filename_col="Nom"))

    seen = []
    result = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "out", ["PNG"],
        progress_cb=lambda done, total: seen.append((done, total)),
    )

    assert seen == [(1, 2), (2, 2)]
    names = {r.item.filename for r in result.results}
    assert names == {"same", "same_2"}


def test_generate_batch_can_be_cancelled(tmp_path):
    rows = [{"Lien": f"https://jelotia.com/{i}"} for i in range(5)]
    plan = build_plan(rows, ColumnMapping(url_col="Lien"))

    # Cancel after the first item.
    state = {"count": 0}

    def should_cancel():
        return state["count"] >= 1

    def progress(done, total):
        state["count"] = done

    result = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "out", ["PNG"],
        progress_cb=progress, should_cancel=should_cancel,
    )
    assert result.cancelled is True
    assert result.succeeded == 1


def test_imposition_payload_prefers_pdf_and_carries_quantities(tmp_path):
    from src.core.engines.qr_batch import imposition_payload

    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "carte_a", "Qte": "3"},
        {"Lien": "https://jelotia.com/b", "Nom": "carte_b", "Qte": "1"},
    ]
    plan = build_plan(
        rows, ColumnMapping(url_col="Lien", filename_col="Nom", quantity_col="Qte")
    )
    result = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "out", ["PNG", "PDF"]
    )

    paths, quantities = imposition_payload(result)
    assert len(paths) == 2
    assert all(p.endswith(".pdf") for p in paths)  # vector output preferred
    assert quantities[paths[0]] == 3
    assert quantities[paths[1]] == 1


def test_batch_cards_flow_into_imposition_pipeline(tmp_path, monkeypatch):
    """Full-circle §14: Excel rows → composed cards (template + variable
    data) → the existing imposition pipeline places every copy on sheets."""
    from src.core.engines.qr_batch import imposition_payload
    from src.core.models.domain import CardTemplate, TemplateQRZone, TemplateTextZone
    from src.core.processors.job_processor import finalize_job_sheets, process_job_files
    from src.utils import config as config_module

    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")
    monkeypatch.setattr(config_module.config, "output_dir", tmp_path / "output")

    template = CardTemplate(
        name="Carte", width_mm=85.0, height_mm=55.0,
        qr_zone=TemplateQRZone(x_mm=58.0, y_mm=20.0, size_mm=24.0),
        texts=[TemplateTextZone(text="{Nom}", x_mm=5.0, y_mm=22.0)],
    )
    rows = [
        {"Lien": "https://jelotia.com/a", "Nom": "Dupont", "Qte": "2"},
        {"Lien": "https://jelotia.com/b", "Nom": "Martin", "Qte": "3"},
    ]
    plan = build_plan(
        rows, ColumnMapping(url_col="Lien", filename_col="Nom", quantity_col="Qte")
    )
    batch = generate_batch(
        QREngine(), plan.items, QRCodeSettings(), tmp_path / "cartes", ["PDF"],
        template=template,
    )
    assert batch.succeeded == 2

    import uuid as uuid_mod
    from pathlib import Path

    from src.core.models.domain import JobSettings

    paths, quantities = imposition_payload(batch)
    job_id = uuid_mod.uuid4()
    settings = JobSettings(
        sheet_width_mm=550.0, sheet_height_mm=890.0, gap_mm=3.0, allow_rotation=True
    )
    items = process_job_files(
        job_id, [Path(p) for p in paths], settings, quantities=quantities
    )
    sheets = finalize_job_sheets(job_id, items, settings, job_name="QR-LOT")

    total_placed = sum(len(s.items) for s in sheets)
    assert total_placed == 5, "2 + 3 copies of the cards must land on the sheets"
    for s in sheets:
        assert s.export_path is not None and s.export_path.exists()


def test_zip_outputs(tmp_path):
    out = tmp_path / "out"
    plan = build_plan(
        [{"Lien": "https://jelotia.com/a", "Nom": "carte_a"}],
        ColumnMapping(url_col="Lien", filename_col="Nom"),
    )
    generate_batch(QREngine(), plan.items, QRCodeSettings(), out, ["PNG", "PDF"])

    zip_path = zip_outputs(out, tmp_path / "lot.zip")
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert set(zf.namelist()) == {"carte_a.png", "carte_a.pdf"}

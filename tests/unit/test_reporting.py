import uuid
from datetime import date, datetime

import openpyxl
import pytest

from src.core.reporting import build_production_report, export_production_xlsx


class _FakeSheet:
    def __init__(self, width_mm, height_mm, fill_rate, poses):
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.fill_rate = fill_rate
        self.items = [{}] * poses


class _FakeJob:
    def __init__(self, name, created_at, sheets, files=1, status="DONE"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.created_at = created_at
        self.status = status
        self.source_paths = ["x.pdf"] * files
        self.sheets = sheets


@pytest.fixture
def jobs():
    return [
        _FakeJob(
            "Badges juin", datetime(2026, 7, 10, 9, 0),
            # 550x890mm = 0.4895 m² per sheet
            [_FakeSheet(550, 890, 80.0, 90), _FakeSheet(550, 890, 40.0, 10)],
            files=100,
        ),
        _FakeJob(
            "Cartes visite", datetime(2026, 7, 12, 14, 0),
            [_FakeSheet(450, 320, 75.0, 24)],
            files=24,
        ),
        _FakeJob("Vieux job", datetime(2026, 6, 1), [], files=3),
    ]


def test_report_aggregates_per_job(jobs):
    report = build_production_report(jobs)
    assert len(report.rows) == 3
    assert report.rows[0].name == "Cartes visite", "tri du plus récent au plus ancien"

    badges = next(r for r in report.rows if r.name == "Badges juin")
    sheet_area = 0.550 * 0.890
    assert badges.area_m2 == pytest.approx(2 * sheet_area, rel=1e-6)
    assert badges.poses == 100
    # Remplissage pondéré par surface : (80 + 40) / 2 = 60 % (surfaces égales)
    assert badges.avg_fill == pytest.approx(60.0, abs=0.01)
    assert badges.waste_m2 == pytest.approx(2 * sheet_area * 0.40, rel=1e-6)


def test_report_date_filter(jobs):
    report = build_production_report(jobs, start=date(2026, 7, 1), end=date(2026, 7, 11))
    assert [r.name for r in report.rows] == ["Badges juin"]

    totals = report.totals
    assert totals["jobs"] == 1
    assert totals["sheets"] == 2


def test_totals_avg_fill_weighted(jobs):
    report = build_production_report(jobs)
    totals = report.totals
    assert totals["poses"] == 124
    # avg global = surface remplie / surface totale
    filled = 2 * 0.4895 * 0.60 + 0.144 * 0.75
    area = 2 * 0.4895 + 0.144
    assert totals["avg_fill"] == pytest.approx(filled / area * 100.0, abs=0.05)


def test_export_xlsx_roundtrip(jobs, tmp_path):
    report = build_production_report(jobs, start=date(2026, 7, 1))
    out = export_production_xlsx(report, tmp_path / "rapport.xlsx")

    wb = openpyxl.load_workbook(str(out))
    ws = wb.active
    values = [[c.value for c in row] for row in ws.iter_rows()]
    flat = str(values)
    assert "Rapport de production JELOTIA" in flat
    assert "Badges juin" in flat and "Cartes visite" in flat
    assert "Vieux job" not in flat, "filtre de dates respecté dans l'export"
    assert "TOTAL" in flat
    wb.close()

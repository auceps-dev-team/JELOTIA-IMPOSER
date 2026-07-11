import uuid
from pathlib import Path

import fitz
import pytest

from src.core.models.domain import JobSettings, PreflightStatus
from src.core.processors.job_processor import finalize_job_sheets, process_job_files


@pytest.fixture
def badge_pdf(tmp_path):
    """A 53x84mm badge, matching the real-world reproduction: sheet 550x890mm,
    gap 3mm, rotation allowed — 50 of these should only reach ~45% fill on
    their own, but 100 of them (two chunks combined) should reach ~80%+."""
    path = tmp_path / "badge.pdf"
    w_pt = (53.0 / 25.4) * 72.0
    h_pt = (84.0 / 25.4) * 72.0
    doc = fitz.open()
    doc.new_page(width=w_pt, height=h_pt)
    doc.save(str(path))
    doc.close()
    return path


def test_finalize_combines_chunks_into_well_filled_sheets(tmp_path, badge_pdf, monkeypatch):
    """
    Regression test for the reported bug: a job split into multiple chunks
    (automation.max_files_per_job) must still pack all of its files together
    when nesting, not one sparse sheet per chunk.
    """
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")
    monkeypatch.setattr(config_module.config, "output_dir", tmp_path / "output")

    job_id = uuid.uuid4()
    settings = JobSettings(sheet_width_mm=550.0, sheet_height_mm=890.0, gap_mm=3.0, allow_rotation=True)

    # Simulate two chunks of 50 files each (matches max_files_per_job=50),
    # both processed under the SAME job_id (as _submit_job now does).
    chunk1_files = process_job_files(job_id, [badge_pdf] * 50, settings)
    chunk2_files = process_job_files(job_id, [badge_pdf] * 50, settings)
    assert len(chunk1_files) == 50
    assert len(chunk2_files) == 50

    all_items = chunk1_files + chunk2_files
    sheets = finalize_job_sheets(job_id, all_items, settings, job_name="Combined Job")

    total_placed = sum(len(s.items) for s in sheets)
    assert total_placed == 100, "all 100 files across both chunks should be placed"

    # 100 items at 90/sheet capacity need exactly 2 sheets (ceil(100/90)) — not
    # 2 independent 50-item sheets each stuck at ~45%. A naive average across
    # sheets would still look ~45% here (dragged down by the unavoidable
    # 10-item remainder sheet), so the real check is sheet 1: with everything
    # combined it should approach the sheet's actual packing capacity instead
    # of being capped at whatever one chunk alone could reach.
    assert len(sheets) == 2, "100 items at ~90/sheet capacity should need exactly 2 sheets"
    sheets_by_fill = sorted(sheets, key=lambda s: s.fill_rate, reverse=True)
    fullest, remainder = sheets_by_fill[0], sheets_by_fill[1]

    assert fullest.fill_rate > 75.0, (
        f"combining both chunks should let sheet 1 approach full packing "
        f"capacity instead of being capped at ~45% by one chunk alone; "
        f"got {fullest.fill_rate:.1f}%"
    )
    assert len(fullest.items) == 90
    assert len(remainder.items) == 10

    for s in sheets:
        assert s.export_path is not None and s.export_path.exists()


def test_finalize_single_chunk_alone_is_the_known_sparse_case(tmp_path, badge_pdf, monkeypatch):
    """Documents the baseline: a single 50-file chunk on its own really can
    only reach ~45% on this sheet size — that's correct given just 50 items,
    not a packing bug. The real fix is combining chunks (see test above)."""
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")
    monkeypatch.setattr(config_module.config, "output_dir", tmp_path / "output")

    job_id = uuid.uuid4()
    settings = JobSettings(sheet_width_mm=550.0, sheet_height_mm=890.0, gap_mm=3.0, allow_rotation=True)

    items = process_job_files(job_id, [badge_pdf] * 50, settings)
    sheets = finalize_job_sheets(job_id, items, settings, job_name="Single Chunk Job")

    assert len(sheets) == 1
    assert 40.0 < sheets[0].fill_rate < 50.0


def test_finalize_persists_item_sources_for_later_regeneration(tmp_path, badge_pdf, monkeypatch):
    """Regression test: finalize_job_sheets deletes the per-job temp dir, but
    the sheets' PlacedItems used to keep referencing the (corrected) files in
    there — so manually repositioning a sheet after the job finished always
    failed with MissingArtworkError. Every referenced source must survive in
    the permanent assets folder, with the items repointed to it."""
    from src.utils import config as config_module
    monkeypatch.setattr(config_module.config, "processing_dir", tmp_path / "processing")
    monkeypatch.setattr(config_module.config, "output_dir", tmp_path / "output")

    job_id = uuid.uuid4()
    settings = JobSettings(
        sheet_width_mm=550.0, sheet_height_mm=890.0, gap_mm=3.0, allow_rotation=True
    )

    items = process_job_files(job_id, [badge_pdf] * 5, settings)
    sheets = finalize_job_sheets(job_id, items, settings, job_name="Persist Sources Job")

    assets_dir = tmp_path / "output" / str(job_id) / "assets"
    placed = [it for sheet in sheets for it in sheet.items]
    assert placed, "the job should have placed items"
    for it in placed:
        src = Path(it.source_path)
        assert src.exists(), f"source artwork must survive the job: {src}"
        assert assets_dir in src.parents, f"source must live in the assets dir: {src}"

    # The ephemeral temp dir is still cleaned up, and copied originals stay put.
    assert not (tmp_path / "processing" / str(job_id)).exists()
    assert badge_pdf.exists()

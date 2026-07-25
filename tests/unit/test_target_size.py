"""Forcing a target file size before imposition.

The client wants to fix each file's printed size on the gamme / job, up front,
instead of only being able to resize a pose after it is laid out. The pose is
placed at the target size and the layout scales the source into it — the same
mechanism as a manual post-imposition resize.
"""

import uuid

import pytest

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
)
from src.core.processors.job_processor import apply_target_size


def _item(width_mm=100.0, height_mm=50.0, dpi=300):
    return FileItem(
        job_id=uuid.uuid4(),
        path="a.pdf",
        format=FileFormat.PDF,
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi,
        color_mode=ColorMode.CMYK,
    )


def test_no_target_leaves_the_file_untouched():
    item = _item(120.0, 80.0, dpi=300)
    apply_target_size(item, JobSettings())  # defaults: 0 / 0
    assert (item.width_mm, item.height_mm, item.dpi) == (120.0, 80.0, 300)


def test_both_axes_forced_to_the_target():
    item = _item(120.0, 80.0)
    apply_target_size(item, JobSettings(target_file_width_mm=60.0,
                                        target_file_height_mm=40.0))
    assert item.width_mm == 60.0
    assert item.height_mm == 40.0


def test_one_axis_zero_keeps_that_axis_natural():
    item = _item(120.0, 80.0)
    apply_target_size(item, JobSettings(target_file_width_mm=90.0,
                                        target_file_height_mm=0.0))
    assert item.width_mm == 90.0
    assert item.height_mm == 80.0, "l'axe à 0 doit rester à la taille d'origine"


def test_shrinking_raises_effective_dpi():
    # Half the size at print -> twice the effective resolution.
    item = _item(100.0, 50.0, dpi=150)
    apply_target_size(item, JobSettings(target_file_width_mm=50.0,
                                        target_file_height_mm=25.0))
    assert item.dpi == 300


def test_enlarging_drops_dpi_so_preflight_can_warn():
    # Double the size at print -> half the effective resolution: an enlarged
    # file must be able to trip the min_dpi warning at its printed size.
    item = _item(100.0, 50.0, dpi=600)
    apply_target_size(item, JobSettings(target_file_width_mm=200.0,
                                        target_file_height_mm=100.0))
    assert item.dpi == 300


def test_effective_dpi_uses_the_worst_axis():
    # Width unchanged (x1), height doubled (x0.5 dpi). The worst axis wins.
    item = _item(100.0, 50.0, dpi=400)
    apply_target_size(item, JobSettings(target_file_width_mm=100.0,
                                        target_file_height_mm=100.0))
    assert item.dpi == 200


def test_degenerate_source_size_is_ignored():
    item = _item(0.0, 0.0)
    apply_target_size(item, JobSettings(target_file_width_mm=50.0,
                                        target_file_height_mm=50.0))
    # No division by zero, and nothing forced onto a sizeless item.
    assert item.width_mm == 0.0 and item.height_mm == 0.0


def test_pipeline_resizes_before_nesting(tmp_path):
    """End-to-end: a real file processed with a target size must be nested at
    that size, not its natural size."""
    import fitz

    from src.core.engines.nesting_engine import NestingEngine, ShelfNestingStrategy
    from src.core.processors.job_processor import process_job_files

    pdf = tmp_path / "art.pdf"
    doc = fitz.open()
    doc.new_page(width=300, height=300)  # ~105.8 x 105.8 mm natural
    doc.save(str(pdf))
    doc.close()

    settings = JobSettings(
        sheet_width_mm=1000.0, sheet_height_mm=1000.0,
        target_file_width_mm=50.0, target_file_height_mm=70.0,
        add_bleed_mm=0.0, min_dpi=1,
    )
    job_id = uuid.uuid4()
    items = process_job_files(job_id, [pdf], settings, work_dir=tmp_path / "w")
    assert items, "le fichier doit être traité"
    for item in items:
        assert item.width_mm == pytest.approx(50.0)
        assert item.height_mm == pytest.approx(70.0)

    sheets = NestingEngine(ShelfNestingStrategy()).process(items, settings)
    placed = [pi for s in sheets for pi in s.items]
    assert placed, "la pose doit être placée"
    # The pose footprint on the sheet is the target size (rotation may swap axes).
    dims = {(round(pi.width_mm), round(pi.height_mm)) for pi in placed}
    assert dims <= {(50, 70), (70, 50)}, f"tailles posées inattendues : {dims}"

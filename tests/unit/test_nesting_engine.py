import uuid
from pathlib import Path

from src.core.engines.nesting_engine import (
    NestingEngine,
    NestingStrategy,
    RectpackNestingStrategy,
    ShelfNestingStrategy,
)
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PlacedItem,
    PreflightStatus,
)


def create_mock_file(
    width: float, height: float, quantity: int = 1, status: PreflightStatus = PreflightStatus.OK
) -> FileItem:
    return FileItem(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        path=Path("mock.pdf"),
        format=FileFormat.PDF,
        width_mm=width,
        height_mm=height,
        dpi=300,
        color_mode=ColorMode.CMYK,
        quantity=quantity,
        preflight_status=status,
    )


def test_rectpack_maxrects_basic():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )

    # 4 squares of 50x50 should fit perfectly in a 100x100 sheet
    items = [create_mock_file(50, 50, quantity=4)]

    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert len(sheet.items) == 4
    # Total area: 4 * (50*50) = 10000. Sheet area: 100*100 = 10000.
    assert sheet.fill_rate == 100.0

    # Check boundaries
    for item in sheet.items:
        assert item.x_mm + item.width_mm <= 100.0
        assert item.y_mm + item.height_mm <= 100.0


def test_rectpack_with_gap():
    # Bin: 100x100. Gap: 10
    # Items: 40x40. With gap, they act as 50x50.
    # So 4 items of 40x40 should fit perfectly with gap=10 on a 100x100 sheet
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=10.0, allow_rotation=False
    )

    items = [create_mock_file(40.0, 40.0, quantity=4)]
    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert len(sheet.items) == 4

    # Actual area placed is 4 * (40*40) = 6400.
    # Fill rate = 6400 / 10000 = 64.0%
    assert sheet.fill_rate == 64.0

    for item in sheet.items:
        # Items are 40x40
        assert item.width_mm == 40.0
        assert item.height_mm == 40.0
        # Their bounds shouldn't exceed 100
        assert item.x_mm + item.width_mm <= 100.0
        assert item.y_mm + item.height_mm <= 100.0


def test_rectpack_rotation():
    # Sheet 100x100. Item is 100x20. Without rotation, it might not fit if x>0.
    # Actually, let's test a 100x20 item rotated.
    # Let's say the item is 120 x 50. Wait, sheet is 100x100. 120x50 won't fit at all.
    # Item is 50 x 100. We pass it as width=50, height=100.
    # If rotation is allowed, it fits either way.
    # To force rotation, let's say sheet is 100x50. Item is 50x100.
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=50.0, gap_mm=0.0, allow_rotation=True
    )

    items = [create_mock_file(50.0, 100.0, quantity=1)]
    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    sheet = sheets[0]
    placed_item = sheet.items[0]

    # Since sheet is 100x50, it MUST be rotated to fit.
    # So actual width/height on the sheet should be 100 and 50.
    assert placed_item.rotated is True
    assert placed_item.width_mm == 100.0
    assert placed_item.height_mm == 50.0


def test_rectpack_overflow_multiple_sheets():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )

    # 5 squares of 50x50. 4 fit on the first sheet, 1 overflows to the second sheet.
    items = [create_mock_file(50, 50, quantity=5)]

    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 2
    assert len(sheets[0].items) == 4
    assert len(sheets[1].items) == 1

    assert sheets[0].sheet_number == 1
    assert sheets[1].sheet_number == 2


def test_nesting_engine_filters_errors():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )

    items = [
        create_mock_file(50, 50, status=PreflightStatus.OK),
        create_mock_file(50, 50, status=PreflightStatus.ERROR),  # Should be ignored
        create_mock_file(50, 50, status=PreflightStatus.WARNING),  # Should be packed
    ]

    strategy = RectpackNestingStrategy(algo_type="maxrects")
    engine = NestingEngine(strategy)

    sheets = engine.process(items, settings)

    assert len(sheets) == 1
    assert len(sheets[0].items) == 2  # Only OK and WARNING


def test_nesting_abstract_strategy():
    class MockStrategy(NestingStrategy):
        def pack(self, items, settings):
            super().pack(items, settings)
            return []
            
    strategy = MockStrategy()
    assert strategy.pack([], JobSettings()) == []


def test_nesting_empty_items():
    strategy = RectpackNestingStrategy(algo_type="maxrects")
    settings = JobSettings()
    assert strategy.pack([], settings) == []


def test_nesting_too_large_item_warning(caplog):
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )

    # Item is larger than the sheet, so it can never be packed
    items = [create_mock_file(200, 200, quantity=1)]

    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 0  # No sheets will be created if nothing was packed
    assert "Could not pack all items! 0/1 packed." in caplog.text


def test_fill_rate_benchmark_above_75_percent():
    """Phase 6: fill_rate ≥ 75% sur corpus homogène (critère d'acceptation).

    Scénario : 100 cartes de visite (85×55mm) sur planche 900×600mm avec gap 3mm.
    Calcul théorique : floor(900/88) × floor(600/58) = 10×10 = 100 items/planche.
    Fill rate = (100 × 85×55) / (900×600) = 86.5% > 75% attendu.
    """
    settings = JobSettings(
        sheet_width_mm=900.0, sheet_height_mm=600.0, gap_mm=3.0, allow_rotation=False
    )
    items = [create_mock_file(85.0, 55.0, quantity=100)]

    strategy = RectpackNestingStrategy(algo_type="maxrects")
    sheets = strategy.pack(items, settings)

    assert len(sheets) > 0, "Aucune planche générée"
    avg_fill = sum(s.fill_rate for s in sheets) / len(sheets)
    assert avg_fill >= 75.0, (
        f"Fill rate {avg_fill:.1f}% inférieur au seuil 75% (corpus cartes de visite)"
    )


def test_shelf_empty_items():
    strategy = ShelfNestingStrategy()
    assert strategy.pack([], JobSettings()) == []


def test_shelf_rows_are_aligned():
    """Mixed sizes should still align into uniform rows: every item sharing a
    row sits on the same y_mm, and rows don't overlap."""
    settings = JobSettings(
        sheet_width_mm=200.0, sheet_height_mm=200.0, gap_mm=2.0, allow_rotation=False
    )
    items = [
        create_mock_file(60, 40, quantity=3),
        create_mock_file(30, 20, quantity=4),
    ]
    strategy = ShelfNestingStrategy()
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert len(sheet.items) == 7

    rows = {}
    for it in sheet.items:
        rows.setdefault(it.y_mm, []).append(it)

    # Each row's items all share the exact same y_mm (uniform row alignment).
    for y, row_items in rows.items():
        assert all(abs(i.y_mm - y) < 1e-6 for i in row_items)

    # No item exceeds sheet bounds.
    for it in sheet.items:
        assert it.x_mm + it.width_mm <= 200.0 + 1e-6
        assert it.y_mm + it.height_mm <= 200.0 + 1e-6

    # No two items on the same row overlap horizontally.
    for y, row_items in rows.items():
        row_items.sort(key=lambda i: i.x_mm)
        for a, b in zip(row_items, row_items[1:]):
            assert a.x_mm + a.width_mm <= b.x_mm + 1e-6


def test_shelf_overflow_multiple_sheets():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )
    items = [create_mock_file(50, 50, quantity=5)]

    strategy = ShelfNestingStrategy()
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 2
    assert sum(len(s.items) for s in sheets) == 5
    assert sheets[0].sheet_number == 1
    assert sheets[1].sheet_number == 2


def test_shelf_too_large_item_skipped(caplog):
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )
    items = [create_mock_file(200, 200, quantity=1)]

    strategy = ShelfNestingStrategy()
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 0
    assert "Could not pack all items" in caplog.text


def test_shelf_new_row_orientation_maximizes_density_not_just_min_height():
    """Regression test: two items each ~half the sheet's width should end up
    side by side on one sheet (like MaxRects), not stranded one-per-sheet.

    Naively minimizing height when opening a new row forces the first item
    into whatever orientation is widest, which can eat the row's remaining
    width and block a second same-sized item from ever joining it — even
    though both would clearly fit side by side in their natural orientation.
    """
    settings = JobSettings(
        sheet_width_mm=900.0, sheet_height_mm=600.0, gap_mm=3.0, allow_rotation=True
    )
    # 420x594mm poster: unrotated leaves two per row (2*420+gap=843<=900);
    # rotated (594x420) would only leave room for one per row.
    items = [create_mock_file(420.0, 594.0, quantity=2)]

    sheets = ShelfNestingStrategy().pack(items, settings)

    assert len(sheets) == 1, "both posters should fit on a single sheet, side by side"
    assert len(sheets[0].items) == 2
    for it in sheets[0].items:
        assert it.rotated is False
    assert sheets[0].fill_rate > 90.0


def test_shelf_new_row_orientation_prefers_natural_fit_for_wide_items():
    """A wide-but-short item (like a business card) should keep its natural
    orientation (more columns per row) rather than rotate to minimize row
    height, which would reduce the number of rows that fit and waste space."""
    settings = JobSettings(
        sheet_width_mm=900.0, sheet_height_mm=600.0, gap_mm=3.0, allow_rotation=True
    )
    items = [create_mock_file(85.0, 55.0, quantity=100)]

    sheets = ShelfNestingStrategy().pack(items, settings)

    assert len(sheets) == 1
    assert len(sheets[0].items) == 100
    assert all(not it.rotated for it in sheets[0].items)
    assert sheets[0].fill_rate >= 85.0


def test_shelf_rotation_used_when_beneficial():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=50.0, gap_mm=0.0, allow_rotation=True
    )
    items = [create_mock_file(50.0, 100.0, quantity=1)]

    strategy = ShelfNestingStrategy()
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    placed_item = sheets[0].items[0]
    assert placed_item.rotated is True
    assert placed_item.width_mm == 100.0
    assert placed_item.height_mm == 50.0


def test_shelf_fill_rate_benchmark_above_75_percent():
    """Same acceptance criterion as the MaxRects benchmark: uniform-size corpus
    should still reach a high fill rate with the row-aligned shelf packer."""
    settings = JobSettings(
        sheet_width_mm=900.0, sheet_height_mm=600.0, gap_mm=3.0, allow_rotation=False
    )
    items = [create_mock_file(85.0, 55.0, quantity=100)]

    strategy = ShelfNestingStrategy()
    sheets = strategy.pack(items, settings)

    assert len(sheets) > 0
    avg_fill = sum(s.fill_rate for s in sheets) / len(sheets)
    assert avg_fill >= 75.0, f"Fill rate {avg_fill:.1f}% inférieur au seuil 75% (shelf packing)"


def test_nesting_engine_uses_shelf_strategy_filters_errors():
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False
    )
    items = [
        create_mock_file(50, 50, status=PreflightStatus.OK),
        create_mock_file(50, 50, status=PreflightStatus.ERROR),
        create_mock_file(50, 50, status=PreflightStatus.WARNING),
    ]

    engine = NestingEngine(ShelfNestingStrategy())
    sheets = engine.process(items, settings)

    assert len(sheets) == 1
    assert len(sheets[0].items) == 2


def test_nesting_engine_applies_margin():
    """Items must stay inside [margin, sheet - margin] on both axes, the
    reported Sheet size stays the full (unshrunk) sheet, and fill_rate is
    computed against the true full sheet area."""
    settings = JobSettings(
        sheet_width_mm=200.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False, margin_mm=10.0
    )
    items = [create_mock_file(50, 50, quantity=2)]

    engine = NestingEngine(ShelfNestingStrategy())
    sheets = engine.process(items, settings)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet.width_mm == 200.0
    assert sheet.height_mm == 100.0
    for it in sheet.items:
        assert it.x_mm >= 10.0 - 1e-6
        assert it.y_mm >= 10.0 - 1e-6
        assert it.x_mm + it.width_mm <= 190.0 + 1e-6
        assert it.y_mm + it.height_mm <= 90.0 + 1e-6

    # Usable area is 180x80; both 50x50 items (5000mm² each) fit side by side.
    expected_fill = (2 * 50 * 50) / (200 * 100) * 100.0
    assert abs(sheet.fill_rate - expected_fill) < 0.1


def test_nesting_engine_margin_too_large_yields_no_sheets(caplog):
    settings = JobSettings(
        sheet_width_mm=100.0, sheet_height_mm=100.0, margin_mm=60.0
    )
    items = [create_mock_file(10, 10, quantity=1)]

    engine = NestingEngine(ShelfNestingStrategy())
    sheets = engine.process(items, settings)

    assert sheets == []
    assert "no usable space" in caplog.text


def create_placed_item(x: float, y: float, width: float, height: float, rotated: bool = False) -> PlacedItem:
    return PlacedItem(
        file_item_id=uuid.uuid4(),
        source_path=Path("mock.pdf"),
        x_mm=x,
        y_mm=y,
        width_mm=width,
        height_mm=height,
        rotated=rotated,
    )


def test_shelf_compaction_relocates_item_across_sheets():
    """Regression test for the scenario described in ShelfNestingStrategy's
    docstring: an item stranded alone in a sparse row (because the forward
    pass only ever looks at rows on the *current* sheet) gets picked up by
    the compaction pass and relocated to a row with room on another sheet.

    Item D (15x35) is too wide to join sheet2's own row (used 90/100, only
    10mm left) so the forward pass strands it in a fresh row of its own.
    Compaction later finds it a home in sheet1's sparse row (20/100 used
    before A/B, 80mm left) instead.
    """
    settings = JobSettings(sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False)
    items = [
        create_mock_file(100, 65),  # A: closes most of sheet1
        create_mock_file(20, 35),  # B: stranded alone in a sparse row on sheet1
        create_mock_file(90, 35),  # C: too wide for B's row -> opens sheet2
        create_mock_file(15, 35),  # D: too wide for C's row -> forward pass strands it too
    ]

    sheets = ShelfNestingStrategy().pack(items, settings)

    assert len(sheets) == 2
    sheet1, sheet2 = sheets

    # D ended up compacted onto sheet1, next to B, instead of stranded alone on sheet2.
    assert len(sheet1.items) == 3
    assert len(sheet2.items) == 1
    relocated = next(it for it in sheet1.items if it.width_mm == 15.0)
    assert relocated.y_mm == 65.0
    assert relocated.x_mm == 20.0  # placed right after B (used_width 20)

    # No overlaps, everything stays in bounds.
    for sheet in sheets:
        for it in sheet.items:
            assert it.x_mm + it.width_mm <= 100.0 + 1e-6
            assert it.y_mm + it.height_mm <= 100.0 + 1e-6


def test_shelf_compaction_disabled_leaves_item_stranded():
    """Same setup as above, but with the compaction pass disabled: item D
    stays stranded alone on sheet2 instead of being relocated to sheet1."""
    settings = JobSettings(sheet_width_mm=100.0, sheet_height_mm=100.0, gap_mm=0.0, allow_rotation=False)
    items = [
        create_mock_file(100, 65),
        create_mock_file(20, 35),
        create_mock_file(90, 35),
        create_mock_file(15, 35),
    ]

    strategy = ShelfNestingStrategy()
    original_compact = ShelfNestingStrategy._compact
    ShelfNestingStrategy._compact = lambda self, *args, **kwargs: None
    try:
        sheets = strategy.pack(items, settings)
    finally:
        ShelfNestingStrategy._compact = original_compact

    assert len(sheets) == 2
    assert len(sheets[0].items) == 2  # A, B only
    assert len(sheets[1].items) == 2  # C, D both stranded together on sheet2


def test_compact_relocates_item_to_better_fit_using_rotation():
    """A sparse row's item that doesn't fit a target row in its stored
    orientation should be rotated to fit if allow_rotation is set."""
    stranded_item = create_placed_item(0, 0, 100, 30)
    sparse_row = {"y": 0, "height": 30, "used_width": 100, "items": [stranded_item]}
    # Tall row with only 50mm of width left: the item's 100x30 orientation
    # doesn't fit that width, but rotated to 30x100 it does.
    target_row = {"y": 30, "height": 100, "used_width": 250, "items": []}
    sheet_shelves = [[sparse_row, target_row]]
    settings = JobSettings(allow_rotation=True)

    ShelfNestingStrategy()._compact(sheet_shelves, settings, gap=0.0, sheet_w=300.0, sheet_h=200.0)

    assert sparse_row["items"] == []
    assert sparse_row["used_width"] == 0.0
    assert len(target_row["items"]) == 1
    relocated = target_row["items"][0]
    assert relocated.rotated is True
    assert relocated.width_mm == 30.0
    assert relocated.height_mm == 100.0
    assert relocated.x_mm == 250.0
    assert relocated.y_mm == 30  # moved to the target row's y


def test_compact_is_all_or_nothing_per_row():
    """If only some of a sparse row's items can be relocated, none of them
    move — a row that only partially empties can't be dropped anyway, so a
    partial drain would just waste items' positions for nothing."""
    item_a = create_placed_item(0, 0, 20, 20)
    item_b = create_placed_item(20, 0, 20, 20)
    sparse_row = {"y": 0, "height": 20, "used_width": 40, "items": [item_a, item_b]}
    # Only 20mm of room left: fits one item, not both.
    target_row = {"y": 20, "height": 20, "used_width": 80, "items": []}
    sheet_shelves = [[sparse_row, target_row]]
    settings = JobSettings(allow_rotation=False)

    ShelfNestingStrategy()._compact(sheet_shelves, settings, gap=0.0, sheet_w=100.0, sheet_h=100.0)

    assert sparse_row["items"] == [item_a, item_b]
    assert sparse_row["used_width"] == 40
    assert target_row["items"] == []


def test_build_sheets_drops_empty_rows_and_shifts_remaining_rows_up():
    """Rows emptied by compaction are removed and the rows below shift up
    to close the gap; sheets left with nothing on them are dropped and the
    rest renumbered."""
    item1 = create_placed_item(0, 0, 80, 50)
    item2 = create_placed_item(0, 100, 50, 30)

    sheet_shelves = [
        [
            {"y": 0, "height": 50, "used_width": 80, "items": [item1]},
            {"y": 55, "height": 40, "used_width": 0.0, "items": []},  # emptied row
            {"y": 100, "height": 30, "used_width": 50, "items": [item2]},
        ],
        [
            {"y": 0, "height": 20, "used_width": 0.0, "items": []},  # emptied sheet
        ],
    ]

    sheets = ShelfNestingStrategy._build_sheets(
        sheet_shelves, job_id=uuid.uuid4(), gap=5.0, sheet_w=100.0, sheet_h=200.0
    )

    assert len(sheets) == 1  # the fully-emptied sheet is dropped
    sheet = sheets[0]
    assert sheet.sheet_number == 1
    assert len(sheet.items) == 2

    # item1's row was untouched (still the first row).
    assert item1.y_mm == 0.0
    # item2 shifted up: the empty row between it and item1 is closed, so it
    # now sits right after item1's row using the standard gap (50 + 5 = 55),
    # not its original y=100.
    assert item2.y_mm == 55.0

    expected_fill = (80 * 50 + 50 * 30) / (100 * 200) * 100.0
    assert abs(sheet.fill_rate - expected_fill) < 1e-6


def test_nesting_guillotine_algo():
    """Vérifie que l'algo guillotine produit aussi des résultats cohérents."""
    settings = JobSettings(
        sheet_width_mm=200.0, sheet_height_mm=200.0, gap_mm=0.0, allow_rotation=False
    )
    items = [create_mock_file(100, 100, quantity=4)]
    strategy = RectpackNestingStrategy(algo_type="guillotine")
    sheets = strategy.pack(items, settings)

    assert len(sheets) == 1
    assert len(sheets[0].items) == 4
    assert sheets[0].fill_rate == 100.0


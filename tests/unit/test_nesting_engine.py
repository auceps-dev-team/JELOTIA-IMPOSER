import uuid
from pathlib import Path

from src.core.engines.nesting_engine import NestingEngine, RectpackNestingStrategy, NestingStrategy
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
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


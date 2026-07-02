from pathlib import Path
from uuid import uuid4

import pytest

from src.core.engines.preflight_engine import PreflightEngine
from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    JobSettings,
    PreflightErrorType,
    PreflightStatus,
)


@pytest.fixture
def default_settings():
    return JobSettings(
        sheet_width_mm=900.0,
        sheet_height_mm=600.0,
        min_dpi=300,
        force_cmyk=True,
    )


@pytest.fixture
def valid_file_item():
    return FileItem(
        job_id=uuid4(),
        path=Path("dummy.jpg"),
        format=FileFormat.JPEG,
        width_mm=100.0,
        height_mm=150.0,
        dpi=300,
        color_mode=ColorMode.CMYK,
    )


def test_preflight_valid_item(valid_file_item, default_settings):
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.OK
    assert len(item.preflight_errors) == 0


def test_preflight_low_resolution(valid_file_item, default_settings):
    valid_file_item.dpi = 150  # Below 300
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.WARNING
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.RESOLUTION_LOW
    assert item.preflight_errors[0].is_blocking is False


def test_preflight_wrong_color_mode(valid_file_item, default_settings):
    valid_file_item.color_mode = ColorMode.RGB
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.WARNING
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.WRONG_COLOR_MODE
    assert item.preflight_errors[0].is_blocking is False


def test_preflight_size_mismatch(valid_file_item, default_settings):
    valid_file_item.width_mm = 1000.0  # Exceeds 900.0
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 1
    assert item.preflight_errors[0].type == PreflightErrorType.SIZE_MISMATCH
    assert item.preflight_errors[0].is_blocking is True


def test_preflight_size_fits_if_rotated(valid_file_item, default_settings):
    # Sheet is 900x600. File is 600x900. Normally exceeds height, but fits if rotated.
    valid_file_item.width_mm = 600.0
    valid_file_item.height_mm = 900.0
    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.OK
    assert len(item.preflight_errors) == 0


def test_preflight_multiple_errors(valid_file_item, default_settings):
    valid_file_item.dpi = 72
    valid_file_item.color_mode = ColorMode.RGB
    valid_file_item.width_mm = 2000.0

    engine = PreflightEngine()
    item = engine.run_preflight(valid_file_item, default_settings)

    assert item.preflight_status == PreflightStatus.ERROR
    assert len(item.preflight_errors) == 3

    error_types = [e.type for e in item.preflight_errors]
    assert PreflightErrorType.RESOLUTION_LOW in error_types
    assert PreflightErrorType.WRONG_COLOR_MODE in error_types
    assert PreflightErrorType.SIZE_MISMATCH in error_types

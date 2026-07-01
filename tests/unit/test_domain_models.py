import pytest
from uuid import UUID
from src.core.models.domain import (
    Job,
    JobStatus,
    FileItem,
    FileFormat,
    ColorMode,
    PreflightStatus,
    Sheet,
)


def test_job_creation():
    job = Job(name="Test Job")
    assert job.name == "Test Job"
    assert job.status == JobStatus.PENDING
    assert isinstance(job.id, UUID)
    assert len(job.files) == 0
    assert len(job.sheets) == 0


def test_file_item_creation():
    job = Job(name="Test Job")
    file_item = FileItem(
        job_id=job.id,
        path="test.pdf",
        format=FileFormat.PDF,
        width_mm=100.0,
        height_mm=150.0,
        dpi=300,
        color_mode=ColorMode.CMYK,
    )
    assert file_item.job_id == job.id
    assert file_item.format == FileFormat.PDF
    assert file_item.preflight_status == PreflightStatus.PENDING
    assert file_item.quantity == 1


def test_sheet_creation():
    job = Job(name="Test Job")
    sheet = Sheet(job_id=job.id, sheet_number=1)
    assert sheet.job_id == job.id
    assert sheet.sheet_number == 1
    assert sheet.width_mm == 900.0
    assert sheet.height_mm == 600.0
    assert len(sheet.items) == 0
    assert sheet.fill_rate == 0.0

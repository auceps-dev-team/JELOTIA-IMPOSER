import pytest
import os
from src.database.repository import DatabaseRepository
from src.core.models.domain import Job, FileItem, FileFormat, ColorMode


@pytest.fixture
def repo():
    # Use an in-memory SQLite database for testing
    repository = DatabaseRepository("sqlite:///:memory:")
    yield repository


def test_create_and_get_job(repo):
    job = Job(name="DB Test Job")
    file_item = FileItem(
        job_id=job.id,
        path="test_db.pdf",
        format=FileFormat.PDF,
        width_mm=200.0,
        height_mm=200.0,
        dpi=300,
        color_mode=ColorMode.CMYK,
    )
    job.files.append(file_item)

    job_id = repo.create_job(job)
    assert job_id is not None

    db_job = repo.get_job(job_id)
    assert db_job is not None
    assert db_job.name == "DB Test Job"
    assert len(db_job.files) == 1
    assert db_job.files[0].path == "test_db.pdf"


def test_update_job_status(repo):
    job = Job(name="Status Test Job")
    job_id = repo.create_job(job)
    
    assert repo.update_job_status(job_id, "PROCESSING") is True
    
    db_job = repo.get_job(job_id)
    assert db_job.status == "PROCESSING"

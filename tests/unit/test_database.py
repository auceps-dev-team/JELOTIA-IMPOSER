import uuid

import pytest

from src.core.models.domain import ColorMode, FileFormat, FileItem, Job, JobSettings, Sheet
from src.database.repository import DatabaseRepository


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


def test_create_job_stub_persists_source_paths(repo):
    """A job stub must be persisted the moment it's submitted, before any
    file has actually been processed, and remember its original source
    files so it can later be resumed."""
    job_id = str(uuid.uuid4())
    paths = ["C:/in/a.pdf", "C:/in/b.pdf"]
    settings = JobSettings()

    assert repo.create_job_stub(job_id, "Stub Job", paths, settings) is True

    db_job = repo.get_job(job_id)
    assert db_job is not None
    assert db_job.status == "PENDING"
    assert db_job.source_paths == paths


def test_create_job_stub_upserts_for_resume(repo):
    """Resuming a failed job resubmits under the same job_id — this must
    update the existing row (and clear stale files/sheets from the previous
    failed attempt) instead of raising a duplicate primary key error."""
    job_id = str(uuid.uuid4())
    settings = JobSettings()

    repo.create_job_stub(job_id, "Resume Job", ["a.pdf"], settings)
    repo.update_job_status(job_id, "ERROR")
    repo.update_job_files(
        job_id,
        [
            FileItem(
                job_id=uuid.UUID(job_id), path="a.pdf", format=FileFormat.PDF,
                width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.CMYK,
            )
        ],
    )

    assert repo.create_job_stub(job_id, "Resume Job", ["a.pdf"], settings) is True

    all_jobs = repo.get_all_jobs()
    assert len(all_jobs) == 1, "resume must not create a duplicate job row"

    db_job = repo.get_job(job_id)
    assert db_job.status == "PENDING"
    assert len(db_job.files) == 0, "stale files from the failed attempt must be cleared"


def test_update_job_files_and_sheets(repo):
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "Files Sheets Job", ["a.pdf"], JobSettings())

    files = [
        FileItem(
            job_id=uuid.UUID(job_id), path="a.pdf", format=FileFormat.PDF,
            width_mm=50, height_mm=50, dpi=300, color_mode=ColorMode.CMYK,
        )
    ]
    assert repo.update_job_files(job_id, files) is True

    sheets = [Sheet(job_id=uuid.UUID(job_id), sheet_number=1, fill_rate=42.0)]
    assert repo.update_job_sheets(job_id, sheets) is True

    db_job = repo.get_job(job_id)
    assert len(db_job.files) == 1
    assert len(db_job.sheets) == 1
    assert db_job.sheets[0].fill_rate == 42.0


def test_recover_processing_jobs_resets_to_pending(repo):
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "Interrupted Job", ["a.pdf"], JobSettings())
    repo.update_job_status(job_id, "PROCESSING")

    recovered = repo.recover_processing_jobs()
    assert recovered == 1

    db_job = repo.get_job(job_id)
    assert db_job.status == "PENDING"


def test_get_all_jobs_returns_every_job(repo):
    repo.create_job_stub(str(uuid.uuid4()), "Job A", ["a.pdf"], JobSettings())
    repo.create_job_stub(str(uuid.uuid4()), "Job B", ["b.pdf"], JobSettings())

    all_jobs = repo.get_all_jobs()
    assert {j.name for j in all_jobs} == {"Job A", "Job B"}

import uuid

import pytest

from src.core.models.domain import (
    ColorMode,
    FileFormat,
    FileItem,
    Job,
    JobSettings,
    PlacedItem,
    PreflightStatus,
    Sheet,
)
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


def test_update_job_sheets_persists_placed_items(repo):
    """Regression test: a Sheet whose items are real PlacedItems (UUID
    file_item_id, Path source_path) must round-trip through the sheets.items
    JSON column. model_dump() in "python" mode leaves those as UUID/Path
    objects, which SQLAlchemy's default JSON serializer can't encode — every
    real sheet (as opposed to the empty-items Sheet used above) hit this."""
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "Placed Items Job", ["a.pdf"], JobSettings())

    file_item_id = uuid.uuid4()
    sheet = Sheet(
        job_id=uuid.UUID(job_id), sheet_number=1,
        items=[
            PlacedItem(
                file_item_id=file_item_id, source_path="a.pdf",
                x_mm=1.0, y_mm=2.0, width_mm=50.0, height_mm=80.0, rotated=True,
            )
        ],
    )
    assert repo.update_job_sheets(job_id, [sheet]) is True

    db_job = repo.get_job(job_id)
    assert len(db_job.sheets) == 1
    persisted_items = db_job.sheets[0].items
    assert len(persisted_items) == 1
    assert persisted_items[0]["file_item_id"] == str(file_item_id)
    assert persisted_items[0]["rotated"] is True
    assert persisted_items[0]["width_mm"] == 50.0


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


def test_create_job_stub_persists_quantities(repo):
    """Every re-submission path (resume, duplicate, gang) rebuilds the job
    from this row — losing the quantities would silently reprint 1 copy."""
    job_id = str(uuid.uuid4())
    quantities = {"C:/in/badge.pdf": 50, "C:/in/carte.pdf": 12}
    repo.create_job_stub(job_id, "Commande", list(quantities), JobSettings(),
                         quantities=quantities)

    db_job = repo.get_job(job_id)
    assert db_job.quantities == quantities

    # Resume upserts the same row: quantities must survive.
    repo.create_job_stub(job_id, "Commande", list(quantities), JobSettings(),
                         quantities=quantities)
    assert repo.get_job(job_id).quantities == quantities


def test_create_job_stub_without_quantities_defaults_to_empty(repo):
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "Sans qty", ["a.pdf"], JobSettings())
    assert repo.get_job(job_id).quantities == {}


def test_schema_migration_adds_quantities_column(tmp_path):
    """Field DBs predate jobs.quantities — it must be added in place."""
    import sqlite3

    db_file = tmp_path / "old2.db"
    con = sqlite3.connect(str(db_file))
    con.execute(
        "CREATE TABLE jobs (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
        "status VARCHAR(50) NOT NULL, created_at DATETIME, settings JSON NOT NULL, "
        "stats JSON NOT NULL, source_paths JSON NOT NULL)"
    )
    con.execute(
        "INSERT INTO jobs (id, name, status, settings, stats, source_paths) "
        "VALUES ('j1', 'Ancien', 'DONE', '{}', '{}', '[]')"
    )
    con.commit()
    con.close()

    repo = DatabaseRepository(str(db_file))
    job = repo.get_job("j1")
    assert job is not None and job.quantities == {}
    assert repo.create_job_stub("j2", "Neuf", ["a.pdf"], JobSettings(),
                                quantities={"a.pdf": 7}) is True
    assert repo.get_job("j2").quantities == {"a.pdf": 7}


def test_delete_job_removes_row_and_children(repo):
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "À supprimer", ["a.pdf"], JobSettings())
    repo.update_job_sheets(job_id, [Sheet(job_id=uuid.UUID(job_id), sheet_number=1)])

    assert repo.delete_job(job_id) is True
    assert repo.get_job(job_id) is None
    assert repo.get_all_jobs() == []
    assert repo.delete_job(job_id) is False  # already gone


def test_archive_job_hides_but_keeps_row(repo):
    job_id = str(uuid.uuid4())
    repo.create_job_stub(job_id, "À archiver", ["a.pdf"], JobSettings())

    assert repo.set_job_archived(job_id, True) is True
    assert repo.get_all_jobs() == [], "un job archivé disparaît de la vue par défaut"
    archived = repo.get_all_jobs(include_archived=True)
    assert len(archived) == 1 and archived[0].archived is True

    assert repo.set_job_archived(job_id, False) is True
    assert len(repo.get_all_jobs()) == 1, "désarchiver le fait réapparaître"


def test_schema_migration_adds_archived_column(tmp_path):
    """A field DB created before jobs.archived must be upgraded in place."""
    import sqlite3

    db_file = tmp_path / "old.db"
    con = sqlite3.connect(str(db_file))
    con.execute(
        "CREATE TABLE jobs (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
        "status VARCHAR(50) NOT NULL, created_at DATETIME, settings JSON NOT NULL, "
        "stats JSON NOT NULL, source_paths JSON NOT NULL)"
    )
    con.execute(
        "INSERT INTO jobs (id, name, status, settings, stats, source_paths) "
        "VALUES ('old-job', 'Ancien', 'DONE', '{}', '{}', '[]')"
    )
    con.commit()
    con.close()

    repo = DatabaseRepository(str(db_file))
    jobs = repo.get_all_jobs()
    assert [j.id for j in jobs] == ["old-job"], "l'ancien job survit à la migration"
    assert repo.set_job_archived("old-job", True) is True
    assert repo.get_all_jobs() == []


def test_qr_batch_history_roundtrip(repo):
    for i in range(3):
        assert repo.add_qr_batch(
            source_name=f"clients_{i}.xlsx", template_name="Badge" if i else None,
            formats="PDF", total=10 + i, succeeded=9 + i, failed=1,
            cancelled=False, out_dir=f"C:/out/{i}",
        ) is True

    batches = repo.get_qr_batches(limit=2)
    assert len(batches) == 2, "limit respectée"
    assert batches[0].source_name == "clients_2.xlsx", "les plus récents d'abord"
    assert batches[0].template_name == "Badge"
    assert batches[0].succeeded == 11


def test_files_processed_today_counts_source_paths(repo):
    a = str(uuid.uuid4())
    repo.create_job_stub(a, "Aujourd'hui A", ["1.pdf", "2.pdf", "3.pdf"], JobSettings())
    b = str(uuid.uuid4())
    repo.create_job_stub(b, "Aujourd'hui B", ["4.pdf"], JobSettings())
    # Archivé : compte quand même (sinon on contournerait le plafond).
    repo.set_job_archived(b, True)

    assert repo.files_processed_today() == 4


def test_get_system_counts(repo):
    a = str(uuid.uuid4())
    repo.create_job_stub(a, "Job A", ["a.pdf"], JobSettings())
    repo.update_job_sheets(a, [Sheet(job_id=uuid.UUID(a), sheet_number=1)])
    b = str(uuid.uuid4())
    repo.create_job_stub(b, "Job B", ["b.pdf"], JobSettings())
    repo.set_job_archived(b, True)

    counts = repo.get_system_counts()
    assert counts["jobs"] == 2  # archivés inclus dans le total
    assert counts["jobs_archived"] == 1
    assert counts["sheets"] == 1


def test_get_dashboard_stats_aggregates_from_db(repo):
    """The dashboard reads live counts from the DB (no more hand-nudged label
    counters): active = PENDING+PROCESSING jobs, preflight_errors = files in
    ERROR state, total_sheets and average fill rate over all sheets."""
    done_id = str(uuid.uuid4())
    repo.create_job_stub(done_id, "Done Job", ["a.pdf"], JobSettings())
    repo.update_job_status(done_id, "DONE")
    repo.update_job_files(
        done_id,
        [
            FileItem(
                job_id=uuid.UUID(done_id), path="ok.pdf", format=FileFormat.PDF,
                width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.CMYK,
                preflight_status=PreflightStatus.OK,
            ),
            FileItem(
                job_id=uuid.UUID(done_id), path="bad.pdf", format=FileFormat.PDF,
                width_mm=10, height_mm=10, dpi=300, color_mode=ColorMode.CMYK,
                preflight_status=PreflightStatus.ERROR,
            ),
        ],
    )
    repo.update_job_sheets(
        done_id,
        [
            Sheet(job_id=uuid.UUID(done_id), sheet_number=1, fill_rate=60.0),
            Sheet(job_id=uuid.UUID(done_id), sheet_number=2, fill_rate=80.0),
        ],
    )

    proc_id = str(uuid.uuid4())
    repo.create_job_stub(proc_id, "Proc Job", ["b.pdf"], JobSettings())
    repo.update_job_status(proc_id, "PROCESSING")

    stats = repo.get_dashboard_stats()
    assert stats["active_jobs"] == 1  # only the PROCESSING job (Done Job is DONE)
    assert stats["preflight_errors"] == 1
    assert stats["total_sheets"] == 2
    assert stats["avg_fill_rate"] == pytest.approx(70.0)
    assert sum(stats["sheets_by_date"].values()) == 2

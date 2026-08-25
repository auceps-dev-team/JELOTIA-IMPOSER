"""M2 / M3 — the schema must be complete whichever path built it.

Two mechanisms have coexisted: the app's own start-up migration
(`DatabaseRepository._migrate_schema`) and Alembic. Alembic's head was two
changes behind the ORM, so `alembic upgrade head` — step 3 of the README quick
start — produced a database missing `jobs.archived` and `jobs.quantities`,
which the app then silently patched on first launch.

These tests pin both paths to the same expected schema, so the two can no
longer drift apart unnoticed.
"""

import sqlite3

import pytest

EXPECTED_INDEXES = {
    "ix_jobs_created_at",
    "ix_jobs_archived",
    "ix_qr_batches_created_at",
    "ix_file_items_job_id",
    "ix_sheets_job_id",
}


def _columns(db_path, table="jobs"):
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _indexes(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'"
            )
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
#  Path 1 — the application's own start-up migration                          #
# --------------------------------------------------------------------------- #

def test_app_startup_builds_a_complete_schema(tmp_path):
    from src.database.repository import DatabaseRepository

    db = tmp_path / "app.db"
    DatabaseRepository(db_url=str(db))

    columns = _columns(db)
    assert {"archived", "quantities"} <= columns
    assert EXPECTED_INDEXES <= _indexes(db)


def test_indexes_are_added_to_a_pre_existing_database(tmp_path):
    """The case that made M2 worthless in the field: create_all() only ever
    indexes a table it creates itself, so an install predating the indexes
    would have kept full-table scans for ever."""
    from src.database.repository import DatabaseRepository

    db = tmp_path / "field.db"
    DatabaseRepository(db_url=str(db))

    # Simulate an older install: drop the indexes, keep the data.
    conn = sqlite3.connect(str(db))
    for name in EXPECTED_INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    conn.commit()
    conn.close()
    assert not _indexes(db) & EXPECTED_INDEXES

    DatabaseRepository(db_url=str(db))  # next launch

    assert EXPECTED_INDEXES <= _indexes(db), (
        "une base déjà déployée doit recevoir les index au démarrage suivant"
    )


def test_startup_migration_is_idempotent(tmp_path):
    from src.database.repository import DatabaseRepository

    db = tmp_path / "twice.db"
    for _ in range(3):
        DatabaseRepository(db_url=str(db))

    assert EXPECTED_INDEXES <= _indexes(db)


# --------------------------------------------------------------------------- #
#  Path 2 — alembic upgrade head, as the README prescribes                    #
# --------------------------------------------------------------------------- #

@pytest.fixture
def alembic_config(tmp_path):
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "src" / "database" / "migrations"))
    db = tmp_path / "alembic.db"
    # env.get_url() honours this now; it used to hardcode the live app database,
    # which made Alembic impossible to test and dangerous to run.
    cfg.cmd_opts = type("Opts", (), {"x": [f"db_url=sqlite:///{db}"]})()
    return cfg, db


def test_alembic_upgrade_head_builds_a_complete_schema(alembic_config):
    from alembic import command

    cfg, db = alembic_config
    command.upgrade(cfg, "head")

    columns = _columns(db)
    assert "archived" in columns, "alembic head en retard sur le modèle ORM"
    assert "quantities" in columns, "alembic head en retard sur le modèle ORM"
    assert EXPECTED_INDEXES <= _indexes(db)


def test_alembic_downgrade_then_upgrade_round_trips(alembic_config):
    from alembic import command

    cfg, db = alembic_config
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "-1")

    assert not _indexes(db) & EXPECTED_INDEXES
    assert "archived" not in _columns(db)

    command.upgrade(cfg, "head")
    assert "archived" in _columns(db)
    assert EXPECTED_INDEXES <= _indexes(db)


def test_alembic_never_targets_the_live_database_when_told_otherwise(alembic_config):
    """get_url() used to ignore every override and always return the app's own
    database — a slip of the command line hit real production jobs."""
    from src.utils.config import config as app_config

    cfg, db = alembic_config
    from alembic import command

    command.upgrade(cfg, "head")

    assert db.exists(), "la base cible explicite doit être utilisée"
    assert str(db) != str(app_config.db_path)

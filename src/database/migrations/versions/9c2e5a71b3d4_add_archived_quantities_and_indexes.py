"""Catch Alembic up with the ORM: jobs.archived, jobs.quantities, and indexes.

The head was two changes behind the models: `jobs.archived` and
`jobs.quantities` were only ever added by the application's own start-up
migration, so `alembic upgrade head` — which the README prescribes as step 3 of
the quick start — produced an incomplete schema that the app then silently
patched on first launch. This revision closes that gap and adds the indexes the
ORM now declares.

Everything is written defensively (existence checks) because the two mechanisms
have coexisted in the field: a given database may already carry some of these.

Revision ID: 9c2e5a71b3d4
Revises: 4bd7b704394b
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9c2e5a71b3d4"
down_revision: Union[str, Sequence[str], None] = "4bd7b704394b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = (
    ("ix_jobs_created_at", "jobs", ["created_at"]),
    ("ix_jobs_archived", "jobs", ["archived"]),
    ("ix_qr_batches_created_at", "qr_batches", ["created_at"]),
    ("ix_file_items_job_id", "file_items", ["job_id"]),
    ("ix_sheets_job_id", "sheets", ["job_id"]),
)


def _existing_columns(table: str) -> set:
    bind = op.get_bind()
    return {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}


def _tables() -> set:
    bind = op.get_bind()
    return set(sa.inspect(bind).get_table_names())


def _create_qr_batches_if_missing(tables: set) -> None:
    """The QR batch history table exists in the ORM but in NO earlier revision:
    `alembic upgrade head` produced a database missing it entirely, and only the
    app's create_all() ever built it. Created here so both paths agree."""
    if "qr_batches" in tables:
        return
    op.create_table(
        "qr_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("source_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("template_name", sa.String(255), nullable=True),
        sa.Column("formats", sa.String(100), nullable=False, server_default=""),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("out_dir", sa.String(1024), nullable=False, server_default=""),
    )


def upgrade() -> None:
    tables = _tables()
    _create_qr_batches_if_missing(tables)
    tables = _tables()
    if "jobs" in tables:
        columns = _existing_columns("jobs")
        if "archived" not in columns:
            op.add_column(
                "jobs",
                sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"),
            )
        if "quantities" not in columns:
            op.add_column(
                "jobs",
                sa.Column("quantities", sa.JSON(), nullable=False, server_default="{}"),
            )

    bind = op.get_bind()
    for index_name, table, columns in _INDEXES:
        if table not in tables:
            continue
        # create_index has no "if not exists"; raw DDL keeps this re-runnable on
        # a database the app's own migration already touched.
        bind.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({', '.join(columns)})"
        )


def downgrade() -> None:
    # `qr_batches` is deliberately NOT dropped: it may already have held real
    # batch history before this revision ran (the app created it via
    # create_all), and a downgrade must not destroy production data to undo a
    # schema change.
    bind = op.get_bind()
    tables = _tables()
    for index_name, table, _columns in _INDEXES:
        if table in tables:
            bind.exec_driver_sql(f"DROP INDEX IF EXISTS {index_name}")

    if "jobs" in tables:
        columns = _existing_columns("jobs")
        # SQLite gained DROP COLUMN in 3.35; batch_alter_table copies the table
        # on older engines.
        with op.batch_alter_table("jobs") as batch:
            if "quantities" in columns:
                batch.drop_column("quantities")
            if "archived" in columns:
                batch.drop_column("archived")

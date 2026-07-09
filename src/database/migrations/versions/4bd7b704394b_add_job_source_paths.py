"""Add jobs.source_paths

Revision ID: 4bd7b704394b
Revises: 1e7d7ef6f9e7
Create Date: 2026-07-09 17:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4bd7b704394b"
down_revision: Union[str, Sequence[str], None] = "1e7d7ef6f9e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "jobs",
        sa.Column("source_paths", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "source_paths")

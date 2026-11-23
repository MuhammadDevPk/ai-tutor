"""add level, page_start, page_end columns to syllabus_nodes

Revision ID: 003
Revises: 002
Create Date: 2026-11-23

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: str | None = '002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE syllabus_nodes
    ADD COLUMN IF NOT EXISTS level INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS page_start INTEGER,
    ADD COLUMN IF NOT EXISTS page_end INTEGER;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE syllabus_nodes
    DROP COLUMN IF EXISTS page_end,
    DROP COLUMN IF EXISTS page_start,
    DROP COLUMN IF EXISTS level;
    """)

"""add fsm_data column to tutor_sessions

Revision ID: 004
Revises: 003
Create Date: 2026-11-23

"""
from collections.abc import Sequence

from alembic import op


revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE tutor_sessions
    ADD COLUMN IF NOT EXISTS fsm_data JSONB NOT NULL DEFAULT '{}'::jsonb;
    """)


def downgrade() -> None:
    op.execute("""
    ALTER TABLE tutor_sessions
    DROP COLUMN IF EXISTS fsm_data;
    """)

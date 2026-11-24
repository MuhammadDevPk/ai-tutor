"""add snapshot to tutor_sessions and indexes for replay and mastery

Revision ID: 005
Revises: 004
Create Date: 2026-11-24

"""
from collections.abc import Sequence

from alembic import op


revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add snapshot column to tutor_sessions for turn-boundary recovery
    op.execute("""
    ALTER TABLE tutor_sessions
    ADD COLUMN IF NOT EXISTS snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;
    """)

    # 2. Add performance indexes for event replay and mastery aggregation
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_session_events_event_type
    ON session_events (event_type);

    CREATE INDEX IF NOT EXISTS idx_session_events_session_event_type
    ON session_events (session_id, event_type);

    CREATE INDEX IF NOT EXISTS idx_tutor_sessions_course_fsm
    ON tutor_sessions (course_id, fsm_state);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS idx_tutor_sessions_course_fsm;
    DROP INDEX IF EXISTS idx_session_events_session_event_type;
    DROP INDEX IF EXISTS idx_session_events_event_type;
    ALTER TABLE tutor_sessions DROP COLUMN IF EXISTS snapshot;
    """)

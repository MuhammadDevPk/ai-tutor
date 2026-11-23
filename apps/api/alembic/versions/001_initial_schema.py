"""initial schema with extensions and 5 core tables

Revision ID: 001
Revises:
Create Date: 2026-11-23

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Enable extensions (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree;")

    # 2. courses table
    op.execute("""
    CREATE TABLE IF NOT EXISTS courses (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL,
        course_code VARCHAR(50) NOT NULL,
        title VARCHAR(255) NOT NULL,
        baseline_skill VARCHAR(100) NOT NULL DEFAULT 'foundational',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_courses_user_id ON courses (user_id);
    """)

    # 3. syllabus_nodes table
    op.execute("""
    CREATE TABLE IF NOT EXISTS syllabus_nodes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        path ltree NOT NULL,
        node_type VARCHAR(50) NOT NULL,
        order_index INTEGER NOT NULL,
        title VARCHAR(255) NOT NULL,
        objectives JSONB NOT NULL DEFAULT '[]'::jsonb,
        key_formulas JSONB NOT NULL DEFAULT '[]'::jsonb,
        summary TEXT,
        mastery_status VARCHAR(50) NOT NULL DEFAULT 'not_started',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_syllabus_nodes_path_gist ON syllabus_nodes USING gist (path);
    CREATE INDEX IF NOT EXISTS idx_syllabus_nodes_course_id ON syllabus_nodes (course_id);
    CREATE INDEX IF NOT EXISTS idx_syllabus_nodes_course_path ON syllabus_nodes (course_id, path);
    """)

    # 4. document_chunks table
    op.execute("""
    CREATE TABLE IF NOT EXISTS document_chunks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        syllabus_path ltree NOT NULL,
        page INTEGER,
        markdown TEXT NOT NULL,
        raw_latex JSONB NOT NULL DEFAULT '[]'::jsonb,
        embedding vector(384),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_document_chunks_syllabus_path_gist ON document_chunks USING gist (syllabus_path);
    CREATE INDEX IF NOT EXISTS idx_document_chunks_course_id ON document_chunks (course_id);
    CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops);
    """)

    # 5. tutor_sessions table
    op.execute("""
    CREATE TABLE IF NOT EXISTS tutor_sessions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
        active_chapter_path ltree NOT NULL,
        current_node_path ltree NOT NULL,
        fsm_state VARCHAR(50) NOT NULL DEFAULT 'ONBOARDING',
        active_turn_id INTEGER NOT NULL DEFAULT 0,
        preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
        resume_stack JSONB NOT NULL DEFAULT '[]'::jsonb,
        board_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_tutor_sessions_active_chapter_gist ON tutor_sessions USING gist (active_chapter_path);
    CREATE INDEX IF NOT EXISTS idx_tutor_sessions_current_node_gist ON tutor_sessions USING gist (current_node_path);
    CREATE INDEX IF NOT EXISTS idx_tutor_sessions_course_id ON tutor_sessions (course_id);
    """)

    # 6. session_events table
    op.execute("""
    CREATE TABLE IF NOT EXISTS session_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        session_id UUID NOT NULL REFERENCES tutor_sessions(id) ON DELETE CASCADE,
        turn_id INTEGER NOT NULL,
        event_type VARCHAR(50) NOT NULL,
        playout_offset_ms INTEGER NOT NULL DEFAULT 0,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_session_events_session_id ON session_events (session_id);
    CREATE INDEX IF NOT EXISTS idx_session_events_session_turn ON session_events (session_id, turn_id);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS session_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS tutor_sessions CASCADE;")
    op.execute("DROP TABLE IF EXISTS document_chunks CASCADE;")
    op.execute("DROP TABLE IF EXISTS syllabus_nodes CASCADE;")
    op.execute("DROP TABLE IF EXISTS courses CASCADE;")

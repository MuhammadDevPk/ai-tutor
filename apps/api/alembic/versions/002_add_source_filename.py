"""add source_filename column to document_chunks

Revision ID: 002
Revises: 001
Create Date: 2026-11-23

"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: str | None = '001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS source_filename VARCHAR(255);

    CREATE INDEX IF NOT EXISTS idx_document_chunks_course_source_file
    ON document_chunks (course_id, source_filename);
    """)


def downgrade() -> None:
    op.execute("""
    DROP INDEX IF EXISTS idx_document_chunks_course_source_file;
    ALTER TABLE document_chunks DROP COLUMN IF EXISTS source_filename;
    """)

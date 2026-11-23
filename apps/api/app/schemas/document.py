from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentUploadResponse(BaseModel):
    pages: int
    chunks: int
    vision_flagged_pages: int
    tree_nodes: int = 0


class DocumentChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    syllabus_path: str
    page: int | None = None
    markdown: str
    raw_latex: list[str] = Field(default_factory=list)
    source_filename: str | None = None
    created_at: datetime | None = None

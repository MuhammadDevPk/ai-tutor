from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SyllabusNodeBase(BaseModel):
    path: str = Field(..., examples=["ch01", "ch01.t01", "ch01.t01.s01"])
    node_type: str = Field(..., examples=["chapter", "topic", "subtopic"])
    order_index: int = Field(..., ge=0)
    title: str = Field(..., max_length=255)
    objectives: list[str] = Field(default_factory=list)
    key_formulas: list[str] = Field(default_factory=list)
    summary: str | None = Field(
        default=None, description="Compact summary <= 250 tokens"
    )
    mastery_status: str = Field(
        default="not_started",
        examples=["not_started", "in_progress", "mastered"],
    )


class SyllabusNodeCreate(SyllabusNodeBase):
    pass


class SyllabusNodeResponse(SyllabusNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    created_at: datetime
    updated_at: datetime


class SyllabusTreeResponse(BaseModel):
    course_id: UUID
    nodes: list[SyllabusNodeResponse]

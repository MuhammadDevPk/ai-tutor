from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    course_id: UUID
    active_chapter_path: str = Field(..., examples=["ch01"])
    current_node_path: str = Field(..., examples=["ch01.t01.s01"])
    preferences: dict[str, Any] = Field(default_factory=dict)


class CreateCourseSessionRequest(BaseModel):
    active_chapter_path: str | None = Field(default=None, examples=["ch01"])


class LiveKitTokenResponse(BaseModel):
    token: str = Field(..., description="LiveKit Room Access JWT")
    url: str = Field(default="", description="LiveKit Server URL")


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    active_chapter_path: str
    current_node_path: str
    fsm_state: str = Field(default="ONBOARDING")
    active_turn_id: int = Field(default=0)
    preferences: dict[str, Any] = Field(default_factory=dict)
    resume_stack: list[dict[str, Any]] = Field(default_factory=list)
    board_snapshot: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    fsm_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SessionEventCreate(BaseModel):
    turn_id: int = Field(..., ge=0)
    event_type: str = Field(
        ...,
        examples=["USER_SPEECH", "AI_SAY", "BOARD_OP", "STATE_CHANGE"],
    )
    playout_offset_ms: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    turn_id: int
    event_type: str
    playout_offset_ms: int
    payload: dict[str, Any]
    created_at: datetime


class FormulaItem(BaseModel):
    latex: str
    label: str = ""
    turn_id: int = 0
    op_id: str = ""


class MisconceptionItem(BaseModel):
    question: str
    clarification: str
    subtopic_path: str = ""
    subtopic_title: str = ""
    turn_id: int = 0


class CheatSheetResponse(BaseModel):
    session_id: UUID
    course_id: UUID
    chapter_path: str
    chapter_title: str
    markdown: str
    formulas: list[FormulaItem] = Field(default_factory=list)
    misconceptions: list[MisconceptionItem] = Field(default_factory=list)


class WeakSubtopicItem(BaseModel):
    subtopic_path: str
    title: str
    interrupt_count: int = 0
    misconception_count: int = 0


class ChapterMasteryItem(BaseModel):
    chapter_path: str
    title: str
    status: str = Field(
        default="not_started",
        description="'completed', 'in_progress', or 'not_started'",
    )
    sessions_count: int = 0
    interrupt_qa_count: int = 0


class CourseMasteryResponse(BaseModel):
    course_id: UUID
    total_chapters: int = 0
    completed_chapters: int = 0
    completion_percentage: float = 0.0
    chapters: list[ChapterMasteryItem] = Field(default_factory=list)
    weak_subtopics: list[WeakSubtopicItem] = Field(default_factory=list)


class SessionReplayResponse(BaseModel):
    session_id: UUID
    course_id: UUID
    active_chapter_path: str
    events: list[SessionEventResponse] = Field(default_factory=list)
    total_events: int = 0


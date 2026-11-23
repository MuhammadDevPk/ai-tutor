from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CourseBase(BaseModel):
    course_code: str = Field(..., max_length=50, examples=["STA301", "MTH5101"])
    title: str = Field(
        ..., max_length=255, examples=["Introduction to Mathematical Statistics"]
    )
    baseline_skill: str = Field(
        default="foundational", max_length=100, examples=["foundational"]
    )


class CourseCreate(CourseBase):
    pass


class CourseUpdate(BaseModel):
    course_code: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=255)
    baseline_skill: str | None = Field(default=None, max_length=100)


class CourseResponse(CourseBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class CourseListResponse(BaseModel):
    items: list[CourseResponse]
    total: int

from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import get_current_user
from app.db.connection import get_db_connection
from app.schemas.course import (
    CourseCreate,
    CourseListResponse,
    CourseResponse,
)

router = APIRouter(prefix="/courses", tags=["courses"])


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    data: CourseCreate,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> CourseResponse:
    query = """
        INSERT INTO courses (user_id, course_code, title, baseline_skill)
        VALUES (%s, %s, %s, %s)
        RETURNING
            id, user_id, course_code, title, baseline_skill, created_at, updated_at;
    """
    params = (
        str(current_user),
        data.course_code,
        data.title,
        data.baseline_skill,
    )
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        await conn.commit()
        if not row:
            raise HTTPException(status_code=500, detail="Failed to create course")
        return CourseResponse.model_validate(row)


@router.get("", response_model=CourseListResponse)
async def list_courses(
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> CourseListResponse:
    query = """
        SELECT id, user_id, course_code, title, baseline_skill, created_at, updated_at
        FROM courses
        WHERE user_id = %s
        ORDER BY created_at DESC;
    """
    params = (str(current_user),)
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()
        items = [CourseResponse.model_validate(r) for r in rows]
        return CourseListResponse(items=items, total=len(items))


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> CourseResponse:
    query = """
        SELECT id, user_id, course_code, title, baseline_skill, created_at, updated_at
        FROM courses
        WHERE id = %s AND user_id = %s;
    """
    params = (str(course_id), str(current_user))
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )
        return CourseResponse.model_validate(row)


@router.delete("/{course_id}", status_code=status.HTTP_200_OK)
async def delete_course(
    course_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> dict[str, str]:
    query = """
        DELETE FROM courses
        WHERE id = %s AND user_id = %s
        RETURNING id;
    """
    params = (str(course_id), str(current_user))
    async with conn.cursor() as cur:
        await cur.execute(query, params)
        row = await cur.fetchone()
        await conn.commit()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )
        return {"status": "deleted", "id": str(course_id)}

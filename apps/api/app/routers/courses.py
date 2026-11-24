from typing import Any
from uuid import UUID

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.auth import get_current_user
from app.db.connection import get_db_connection
from app.db.ltree_repository import ScopedLtreeRepository, sanitize_ltree_path
from app.exports.mastery import get_course_mastery
from app.ingestion.embeddings import BaseEmbedder, FastEmbedder
from app.ingestion.gemini_client import GeminiClient, get_gemini_client
from app.ingestion.service import IngestionService
from app.ingestion.tree_extractor import assemble_tree
from app.schemas.course import (
    CourseCreate,
    CourseListResponse,
    CourseResponse,
)
from app.schemas.document import (
    DocumentChunkResponse,
    DocumentUploadResponse,
)
from app.schemas.session import (
    CourseMasteryResponse,
    CreateCourseSessionRequest,
    SessionResponse,
)
from app.schemas.syllabus import (
    SyllabusTreeResponse,
)
from app.tutor.service import TutorService

router = APIRouter(prefix="/courses", tags=["courses"])


async def _verify_course_owner(
    course_id: UUID,
    user_id: UUID,
    conn: psycopg.AsyncConnection[Any],
) -> None:
    query = "SELECT id FROM courses WHERE id = %s AND user_id = %s;"
    async with conn.cursor() as cur:
        await cur.execute(query, (str(course_id), str(user_id)))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Course not found"
            )


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


def get_embedder() -> BaseEmbedder:
    return FastEmbedder()


@router.post(
    "/{course_id}/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_document(
    course_id: UUID,
    file: UploadFile = File(...),
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
    gemini_client: GeminiClient | None = Depends(get_gemini_client),
    embedder: BaseEmbedder = Depends(get_embedder),
) -> DocumentUploadResponse:
    await _verify_course_owner(course_id, current_user, conn)

    # Enforce PDF only
    filename = file.filename or ""
    content_type = file.content_type or ""
    if not (filename.lower().endswith(".pdf") or content_type == "application/pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    use_tree_extraction = gemini_client is not None
    service = IngestionService(
        pool_or_conn=conn,
        embedder=embedder,
        gemini_client=gemini_client,
    )
    try:
        result = await service.ingest_document(
            course_id=course_id,
            document_bytes=file_bytes,
            filename=filename or "document.pdf",
            use_tree_extraction=use_tree_extraction,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    tree_count = result.tree_nodes
    if tree_count == 0:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) as cnt FROM syllabus_nodes WHERE course_id = %s;",
                (str(course_id),),
            )
            count_row = await cur.fetchone()
            if count_row:
                tree_count = count_row["cnt"]

    return DocumentUploadResponse(
        pages=result.pages,
        chunks=result.chunks,
        vision_flagged_pages=result.vision_flagged_pages,
        tree_nodes=tree_count,
    )


@router.get(
    "/{course_id}/syllabus",
    response_model=SyllabusTreeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_course_syllabus(
    course_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> SyllabusTreeResponse:
    await _verify_course_owner(course_id, current_user, conn)

    query = """
        SELECT id, course_id, path, node_type, order_index, title, level,
               page_start, page_end, objectives, key_formulas, summary,
               mastery_status, created_at, updated_at
        FROM syllabus_nodes
        WHERE course_id = %s
        ORDER BY path ASC, order_index ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(query, (str(course_id),))
        rows = await cur.fetchall()

    roots = assemble_tree(rows)
    return SyllabusTreeResponse(course_id=course_id, nodes=roots)


@router.get(
    "/{course_id}/syllabus/chunks",
    response_model=list[DocumentChunkResponse],
    status_code=status.HTTP_200_OK,
)
async def get_syllabus_chunks(
    course_id: UUID,
    path: str = Query(..., description="PostgreSQL ltree path scope"),
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> list[DocumentChunkResponse]:
    await _verify_course_owner(course_id, current_user, conn)

    try:
        valid_path = sanitize_ltree_path(path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid ltree path: {e}",
        ) from e

    repo = ScopedLtreeRepository(conn)
    rows = await repo.query_document_chunks(
        course_id=course_id,
        scope_path=valid_path,
        limit=100,
    )
    return [DocumentChunkResponse.model_validate(r) for r in rows]


@router.post(
    "/{course_id}/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_course_session(
    course_id: UUID,
    data: CreateCourseSessionRequest | None = None,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> SessionResponse:
    await _verify_course_owner(course_id, current_user, conn)
    service = TutorService(pool_or_conn=conn)
    active_chapter = data.active_chapter_path if data else None
    session = await service.start_session(
        course_id=course_id,
        user_id=current_user,
        active_chapter_path=active_chapter,
    )
    await conn.commit()
    return SessionResponse.model_validate(session)


@router.get(
    "/{course_id}/mastery",
    response_model=CourseMasteryResponse,
    status_code=status.HTTP_200_OK,
)
async def get_course_mastery_endpoint(
    course_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> CourseMasteryResponse:
    """Get read-only course mastery stats and weak subtopic rankings."""
    await _verify_course_owner(course_id, current_user, conn)
    return await get_course_mastery(conn, course_id)


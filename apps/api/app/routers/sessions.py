"""Router for session lifecycle, replay, study export, and LiveKit token minting."""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse
from livekit.api import AccessToken, VideoGrants

from app.auth import get_current_user
from app.config import settings
from app.db.connection import get_db_connection
from app.exports.cheat_sheet import generate_cheat_sheet
from app.schemas.session import (
    CheatSheetResponse,
    LiveKitTokenResponse,
    SessionEventResponse,
    SessionReplayResponse,
    SessionResponse,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _verify_session_owner(
    session_id: UUID,
    user_id: UUID,
    conn: psycopg.AsyncConnection[Any],
) -> dict[str, Any]:
    """Verify session exists and caller is course owner."""
    query = """
        SELECT
            ts.id,
            ts.course_id,
            ts.active_chapter_path::text AS active_chapter_path,
            ts.current_node_path::text AS current_node_path,
            ts.fsm_state,
            ts.active_turn_id,
            ts.preferences,
            ts.resume_stack,
            ts.board_snapshot,
            ts.fsm_data,
            ts.snapshot,
            ts.created_at,
            ts.updated_at,
            c.user_id
        FROM tutor_sessions ts
        JOIN courses c ON ts.course_id = c.id
        WHERE ts.id = %s;
    """
    async with conn.cursor() as cur:
        await cur.execute(query, (str(session_id),))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        owner_id = row["user_id"] if isinstance(row, dict) else row[13]
        if str(owner_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )
        if isinstance(row, dict):
            return dict(row)
        else:
            return {
                "id": row[0],
                "course_id": row[1],
                "active_chapter_path": row[2],
                "current_node_path": row[3],
                "fsm_state": row[4],
                "active_turn_id": row[5],
                "preferences": row[6] or {},
                "resume_stack": row[7] or [],
                "board_snapshot": row[8] or {},
                "fsm_data": row[9] or {},
                "snapshot": row[10] or row[8] or {},
                "created_at": row[11],
                "updated_at": row[12],
                "user_id": row[13],
            }


def _row_to_event(r: Any) -> SessionEventResponse:
    """Validate a session_events row whether dict or tuple."""
    if isinstance(r, dict):
        return SessionEventResponse.model_validate(r)
    return SessionEventResponse(
        id=r[0],
        session_id=r[1],
        turn_id=r[2],
        event_type=r[3],
        playout_offset_ms=r[4],
        payload=r[5] or {},
        created_at=r[6],
    )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_session(
    session_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> SessionResponse:
    """Fetch session with turn-boundary snapshot for reload recovery."""
    row = await _verify_session_owner(session_id, current_user, conn)
    # Ensure snapshot is populated from board_snapshot if empty
    if not row.get("snapshot") and row.get("board_snapshot"):
        row["snapshot"] = row["board_snapshot"]
    return SessionResponse.model_validate(row)


@router.get(
    "/{session_id}/events",
    response_model=list[SessionEventResponse],
    status_code=status.HTTP_200_OK,
)
async def get_session_events(
    session_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> list[SessionEventResponse]:
    """Fetch all session events ordered by turn and creation time."""
    await _verify_session_owner(session_id, current_user, conn)
    query = """
        SELECT
            id, session_id, turn_id, event_type,
            playout_offset_ms, payload, created_at
        FROM session_events
        WHERE session_id = %s
        ORDER BY turn_id ASC, created_at ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(query, (str(session_id),))
        rows = await cur.fetchall()
        return [_row_to_event(r) for r in rows]


@router.get(
    "/{session_id}/cheat-sheet",
    response_model=CheatSheetResponse,
    status_code=status.HTTP_200_OK,
)
async def get_session_cheat_sheet(
    session_id: UUID,
    format: str = Query("json", pattern="^(json|markdown|md)$"),
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> CheatSheetResponse | Response:
    """Generate or export a Markdown cheat sheet for the session."""
    await _verify_session_owner(session_id, current_user, conn)
    cheat_sheet = await generate_cheat_sheet(conn, session_id)
    if format in ("markdown", "md"):
        filename = f"cheat-sheet-{session_id}.md"
        return PlainTextResponse(
            content=cheat_sheet.markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return cheat_sheet


@router.get(
    "/{session_id}/replay",
    response_model=SessionReplayResponse,
    status_code=status.HTTP_200_OK,
)
async def get_session_replay(
    session_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> SessionReplayResponse:
    """Get replay bundle with all chronological events for timeline scrubbing."""
    session_info = await _verify_session_owner(session_id, current_user, conn)
    events_query = """
        SELECT
            id, session_id, turn_id, event_type,
            playout_offset_ms, payload, created_at
        FROM session_events
        WHERE session_id = %s
        ORDER BY turn_id ASC, created_at ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(events_query, (str(session_id),))
        rows = await cur.fetchall()
        events = [_row_to_event(r) for r in rows]

    return SessionReplayResponse(
        session_id=session_id,
        course_id=UUID(str(session_info["course_id"])),
        active_chapter_path=str(session_info["active_chapter_path"]),
        events=events,
        total_events=len(events),
    )


@router.post(
    "/{session_id}/livekit-token",
    response_model=LiveKitTokenResponse,
    status_code=status.HTTP_200_OK,
)
async def get_livekit_token(
    session_id: UUID,
    current_user: UUID = Depends(get_current_user),
    conn: psycopg.AsyncConnection[Any] = Depends(get_db_connection),
) -> LiveKitTokenResponse:
    """Mint a LiveKit room token bound to a verified tutor session."""
    await _verify_session_owner(session_id, current_user, conn)

    # Resolve display name
    name = (
        settings.DEV_USER_EMAIL
        if str(current_user) == str(settings.DEV_USER_ID)
        else str(current_user)
    )

    api_key = settings.LIVEKIT_API_KEY or "devkey"
    api_secret = settings.LIVEKIT_API_SECRET or "secret_key_at_least_16_chars_long"

    token = (
        AccessToken(api_key, api_secret)
        .with_identity(str(current_user))
        .with_name(name)
        .with_grants(
            VideoGrants(
                room_join=True,
                room=str(session_id),
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .with_ttl(datetime.timedelta(minutes=15))
        .to_jwt()
    )

    return LiveKitTokenResponse(token=token, url=settings.LIVEKIT_URL)


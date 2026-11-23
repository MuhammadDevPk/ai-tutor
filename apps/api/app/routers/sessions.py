"""Router for session lifecycle and LiveKit token minting."""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from livekit.api import AccessToken, VideoGrants

from app.auth import get_current_user
from app.config import settings
from app.db.connection import get_db_connection
from app.schemas.session import LiveKitTokenResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
    query = """
        SELECT ts.id, c.user_id
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
        owner_id = row["user_id"] if isinstance(row, dict) else row[1]
        if str(owner_id) != str(current_user):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found",
            )

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

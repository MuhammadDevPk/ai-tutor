from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import create_access_token
from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token(user_id=settings.DEV_USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def test_course(auth_headers: dict[str, str]) -> str:
    code = f"SESS{uuid4().hex[:4].upper()}"
    resp = client.post(
        "/courses",
        json={"course_code": code, "title": "Session Test Course"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    course_id = str(resp.json()["id"])
    return course_id


def test_create_session_unauthenticated(test_course: str):
    resp = client.post(f"/courses/{test_course}/sessions")
    assert resp.status_code == 401


def test_create_session_other_user_forbidden(test_course: str):
    other_user_token = create_access_token(user_id=uuid4())
    resp = client.post(
        f"/courses/{test_course}/sessions",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert resp.status_code == 404


def test_create_session_success(auth_headers: dict[str, str], test_course: str):
    resp = client.post(
        f"/courses/{test_course}/sessions",
        json={"active_chapter_path": "ch01"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "id" in data
    assert data["course_id"] == test_course
    assert data["active_chapter_path"] == "ch01"
    assert data["fsm_state"] == "ONBOARDING"
    assert data["active_turn_id"] == 0


def test_livekit_token_endpoint_lifecycle(
    auth_headers: dict[str, str], test_course: str
):
    # 1. Create a tutor session
    create_resp = client.post(
        f"/courses/{test_course}/sessions",
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    session_id = create_resp.json()["id"]

    # 2. Unauthenticated request -> 401
    unauth_resp = client.post(f"/sessions/{session_id}/livekit-token")
    assert unauth_resp.status_code == 401

    # 3. Non-existent session -> 404
    non_existent = uuid4()
    not_found_resp = client.post(
        f"/sessions/{non_existent}/livekit-token",
        headers=auth_headers,
    )
    assert not_found_resp.status_code == 404

    # 4. Another user's session -> 404
    other_user_token = create_access_token(user_id=uuid4())
    cross_user_resp = client.post(
        f"/sessions/{session_id}/livekit-token",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert cross_user_resp.status_code == 404

    # 5. Session owner mints token -> 200 with decodable JWT
    token_resp = client.post(
        f"/sessions/{session_id}/livekit-token",
        headers=auth_headers,
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "token" in token_data
    jwt_token = token_data["token"]

    # Decode and verify JWT claims
    claims = jwt.decode(jwt_token, options={"verify_signature": False})
    assert claims["sub"] == str(settings.DEV_USER_ID)
    assert claims["name"] == settings.DEV_USER_EMAIL

    # TTL is 15 minutes = 900 seconds
    issued_at = claims.get("nbf") or claims.get("iat") or 0
    ttl_seconds = claims["exp"] - issued_at
    assert ttl_seconds == 900

    # Video grants: room_join, room, can_publish, can_subscribe, can_publish_data
    video_grants = claims.get("video", {})
    assert video_grants.get("room") == session_id
    assert video_grants.get("roomJoin") is True
    assert video_grants.get("canPublish") is True
    assert video_grants.get("canSubscribe") is True
    assert video_grants.get("canPublishData") is True

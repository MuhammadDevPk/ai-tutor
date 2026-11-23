from uuid import uuid4

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


def test_course_crud_lifecycle(auth_headers: dict[str, str]):
    code = f"TEST{uuid4().hex[:4].upper()}"
    # 1. Create course
    create_payload = {
        "course_code": code,
        "title": "Automated Test Course",
        "baseline_skill": "foundational",
    }
    create_resp = client.post("/courses", json=create_payload, headers=auth_headers)
    assert create_resp.status_code == 201, create_resp.text
    course_data = create_resp.json()
    course_id = course_data["id"]
    assert course_data["course_code"] == code
    assert course_data["user_id"] == str(settings.DEV_USER_ID)

    # 2. Get course
    get_resp = client.get(f"/courses/{course_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == course_id

    # 3. List courses
    list_resp = client.get("/courses", headers=auth_headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    ids = [c["id"] for c in list_data["items"]]
    assert course_id in ids

    # 4. Delete course
    del_resp = client.delete(f"/courses/{course_id}", headers=auth_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # 5. Confirm deletion
    get_after_del = client.get(f"/courses/{course_id}", headers=auth_headers)
    assert get_after_del.status_code == 404


def test_get_course_other_user_forbidden(auth_headers: dict[str, str]):
    # Requesting a random nonexistent course returns 404
    random_id = uuid4()
    resp = client.get(f"/courses/{random_id}", headers=auth_headers)
    assert resp.status_code == 404


def test_course_cross_user_isolation(auth_headers: dict[str, str]):
    """Adversarial check: Course created by User A cannot be accessed by User B."""
    # 1. User A creates a course
    create_resp = client.post(
        "/courses",
        json={
            "course_code": f"ISO{uuid4().hex[:4].upper()}",
            "title": "Isolation Course",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    try:
        # 2. User B tries to access User A's course
        user_b_id = uuid4()
        token_b = create_access_token(user_id=user_b_id)
        user_b_headers = {"Authorization": f"Bearer {token_b}"}

        get_resp = client.get(f"/courses/{course_id}", headers=user_b_headers)
        assert get_resp.status_code == 404

        # 3. User B tries to delete User A's course
        del_resp = client.delete(f"/courses/{course_id}", headers=user_b_headers)
        assert del_resp.status_code == 404

        # 4. User A can still access their course
        get_owner_resp = client.get(f"/courses/{course_id}", headers=auth_headers)
        assert get_owner_resp.status_code == 200
    finally:
        # Clean up
        client.delete(f"/courses/{course_id}", headers=auth_headers)

from uuid import UUID

from fastapi.testclient import TestClient

from app.auth import create_access_token, seed_dev_user
from app.config import settings
from app.main import app

client = TestClient(app)


def test_login_success():
    dev_user = seed_dev_user()
    response = client.post(
        "/auth/login",
        json={"email": dev_user["email"], "password": dev_user["password"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_invalid_password():
    dev_user = seed_dev_user()
    response = client.post(
        "/auth/login",
        json={"email": dev_user["email"], "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


def test_login_unknown_email():
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anypassword"},
    )
    assert response.status_code == 401


def test_protected_route_without_token():
    response = client.get("/courses")
    assert response.status_code == 401


def test_protected_route_with_invalid_token():
    response = client.get(
        "/courses", headers={"Authorization": "Bearer not-a-valid-jwt"}
    )
    assert response.status_code == 401


def test_access_token_decodes_to_uuid():
    token = create_access_token(user_id=settings.DEV_USER_ID)
    import jwt

    payload = jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
    )
    user_id_raw = payload.get("sub")
    assert user_id_raw is not None
    user_id = UUID(user_id_raw)
    assert isinstance(user_id, UUID)
    assert user_id == settings.DEV_USER_ID

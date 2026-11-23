from fastapi import APIRouter, HTTPException, status

from app.auth import create_access_token, seed_dev_user, verify_password
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest) -> TokenResponse:
    dev_user = seed_dev_user()
    email_matches = credentials.email == dev_user["email"]
    password_valid = verify_password(credentials.password, dev_user["password_hash"])
    if not (email_matches and password_valid):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user_id=dev_user["user_id"])
    return TokenResponse(access_token=token, token_type="bearer")

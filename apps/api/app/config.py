import os
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv

# Load .env if present
env_file = Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()


class Settings:
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:localdev@localhost:5432/ai_tutor"
    )
    JWT_SECRET: str = os.environ.get(
        "JWT_SECRET", "dev-secret-key-change-in-production"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
    DEV_USER_EMAIL: str = os.environ.get("DEV_USER_EMAIL", "dev@example.com")
    DEV_USER_PASSWORD: str = os.environ.get("DEV_USER_PASSWORD", "devpassword123")
    DEV_USER_ID: UUID = UUID(
        os.environ.get("DEV_USER_ID", "00000000-0000-0000-0000-000000000001")
    )


settings = Settings()

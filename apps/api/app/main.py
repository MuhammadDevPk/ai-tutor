from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.db.connection import close_db_pool, init_db_pool
from app.routers import auth, courses
from app.schemas.events import (
    AudioSegmentStartEvent,
    AvatarCueEvent,
    BoardOp,
    BoardScheduleEvent,
    BoardSelectionEvent,
    InterruptFlushEvent,
    LayoutOverrideEvent,
    PlayoutPauseEvent,
    PlayoutResumeEvent,
)
from app.schemas.session import (
    SessionCreate,
    SessionEventCreate,
    SessionEventResponse,
    SessionResponse,
)
from app.schemas.syllabus import (
    SyllabusNodeCreate,
    SyllabusNodeResponse,
    SyllabusTreeResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db_pool()
    yield
    await close_db_pool()


app = FastAPI(
    title="AI Video Tutor API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(courses.router)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    models: Sequence[tuple[type[BaseModel], Literal["validation", "serialization"]]] = [
        (AudioSegmentStartEvent, "validation"),
        (BoardScheduleEvent, "validation"),
        (PlayoutPauseEvent, "validation"),
        (PlayoutResumeEvent, "validation"),
        (InterruptFlushEvent, "validation"),
        (AvatarCueEvent, "validation"),
        (BoardSelectionEvent, "validation"),
        (LayoutOverrideEvent, "validation"),
        (BoardOp, "validation"),
        (SyllabusNodeCreate, "validation"),
        (SyllabusNodeResponse, "validation"),
        (SyllabusTreeResponse, "validation"),
        (SessionCreate, "validation"),
        (SessionResponse, "validation"),
        (SessionEventCreate, "validation"),
        (SessionEventResponse, "validation"),
    ]
    _, defs = models_json_schema(models, ref_template="#/components/schemas/{model}")
    openapi_schema.setdefault("components", {}).setdefault("schemas", {})
    extra_schemas = defs.get("$defs", {})
    openapi_schema["components"]["schemas"].update(extra_schemas)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

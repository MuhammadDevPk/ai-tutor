"""TutorService tying FSM + router + parser + repository behind async methods."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from app.db.connection import get_db_pool
from app.db.ltree_repository import ScopedLtreeRepository
from app.llm.router import LLMRouter
from app.llm.stream_parser import ParsedEvent
from app.tutor.budget import PromptAssembler
from app.tutor.fsm import PedagogicalFSM, StateEvent, TutorSession, TutorState


class TutorService:
    """Tutor service facade managing session lifecycle and message dispatch."""

    def __init__(
        self,
        pool_or_conn: Any = None,
        router: LLMRouter | None = None,
        repository: ScopedLtreeRepository | None = None,
        assembler: PromptAssembler | None = None,
    ) -> None:
        self._pool_or_conn = pool_or_conn
        self.router = router if router is not None else LLMRouter()
        if repository is not None:
            self.repository = repository
        else:
            self.repository = ScopedLtreeRepository(self._get_active_pool_or_conn())
        self.assembler = assembler if assembler is not None else PromptAssembler()
        self.fsm = PedagogicalFSM(
            repository=self.repository,
            router=self.router,
            assembler=self.assembler,
        )

    def _get_active_pool_or_conn(self) -> Any:
        if self._pool_or_conn is not None:
            return self._pool_or_conn
        return get_db_pool()

    @asynccontextmanager
    async def _get_conn(self) -> AsyncGenerator[Any, None]:
        target = self._get_active_pool_or_conn()
        if callable(getattr(target, "connection", None)):
            async with target.connection() as conn:
                yield conn
        else:
            yield target

    async def start_session(
        self,
        course_id: UUID,
        user_id: UUID,
        active_chapter_path: str | None = None,
    ) -> TutorSession:
        """Create a new tutor session initialized in ONBOARDING state."""
        session_id = uuid4()
        async with self._get_conn() as conn:
            # 1. Determine active chapter if not specified
            chapter_path = active_chapter_path
            if not chapter_path:
                query = (
                    "SELECT path::text FROM syllabus_nodes "
                    "WHERE course_id = %s "
                    "AND (node_type = 'chapter' OR nlevel(path) = 1) "
                    "ORDER BY order_index ASC LIMIT 1;"
                )
                async with conn.cursor() as cur:
                    await cur.execute(query, (str(course_id),))
                    row = await cur.fetchone()
                    if row:
                        chapter_path = row["path"] if isinstance(row, dict) else row[0]
                    else:
                        chapter_path = "ch01"

            # 2. Determine initial current_node_path (first subtopic)
            subquery = (
                "SELECT path::text FROM syllabus_nodes "
                "WHERE course_id = %s AND path <@ %s::ltree AND path != %s::ltree "
                "ORDER BY order_index ASC LIMIT 1;"
            )
            node_path = chapter_path
            async with conn.cursor() as cur:
                await cur.execute(
                    subquery, (str(course_id), chapter_path, chapter_path)
                )
                sub_row = await cur.fetchone()
                if sub_row:
                    node_path = (
                        sub_row["path"] if isinstance(sub_row, dict) else sub_row[0]
                    )

            # 3. Insert tutor_sessions row
            insert_query = (
                "INSERT INTO tutor_sessions "
                "(id, course_id, active_chapter_path, current_node_path, fsm_state, "
                " active_turn_id, preferences, resume_stack, board_snapshot, fsm_data) "
                "VALUES (%s, %s, %s::ltree, %s::ltree, %s, %s, "
                "        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb) "
                "RETURNING created_at, updated_at;"
            )
            params = (
                str(session_id),
                str(course_id),
                chapter_path,
                node_path,
                TutorState.ONBOARDING.value,
                0,
                json.dumps({}),
                json.dumps([]),
                json.dumps({}),
                json.dumps({}),
            )
            async with conn.cursor() as cur:
                await cur.execute(insert_query, params)
                res = await cur.fetchone()
                created_at = res["created_at"] if isinstance(res, dict) else res[0]
                updated_at = res["updated_at"] if isinstance(res, dict) else res[1]

            # 4. Log initial state change event in session_events
            await self.fsm.log_event(
                conn,
                session_id,
                0,
                "STATE_CHANGE",
                {
                    "from_state": "",
                    "to_state": TutorState.ONBOARDING.value,
                    "current_node_path": node_path,
                    "reason": "session_created",
                },
            )

            # Return initialized TutorSession
            return TutorSession(
                id=session_id,
                course_id=course_id,
                active_chapter_path=chapter_path,
                current_node_path=node_path,
                fsm_state=TutorState.ONBOARDING.value,
                active_turn_id=0,
                preferences={},
                resume_stack=[],
                board_snapshot={},
                fsm_data={},
                created_at=created_at,
                updated_at=updated_at,
            )

    async def get_session(self, session_id: UUID) -> TutorSession:
        """Fetch session by ID."""
        async with self._get_conn() as conn:
            return await self.fsm.get_session(conn, session_id)

    async def handle_student_message(
        self,
        session_id: UUID,
        text: str,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Dispatch student message to the FSM and yield parsed + state events."""
        async with self._get_conn() as conn:
            session = await self.fsm.get_session(conn, session_id)
            async for ev in self.fsm.handle_turn(conn, session, student_text=text):
                yield ev

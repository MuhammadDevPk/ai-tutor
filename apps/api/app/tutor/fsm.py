"""Explicit 5-State Pedagogical FSM for AI Video Tutor.

States:
- ONBOARDING: Collect student baseline and orientation.
- TEACH_STEP: Deliver chapter subtopic with ltree-fenced RAG and protocol lines.
- MICRO_CHECK: Evaluate student answers and decide progression or remedial loop.
- INTERRUPT_QA: Handle mid-step student questions with scoped RAG and clean resumption.
- RECAP: Summarize chapter, record node mastery, and conclude cleanly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, cast
from uuid import UUID

from app.db.ltree_repository import ScopedLtreeRepository
from app.llm.providers import ChatMessage
from app.llm.router import LLMRouter
from app.llm.stream_parser import (
    ClearEvent,
    CtrlEvent,
    DiagramEvent,
    LatexEvent,
    LineStreamParser,
    ParsedEvent,
    PlotEvent,
    SayEvent,
    sanitize_say_text,
)
from app.tutor.budget import (
    WHITEBOARD_SUMMARY_CEILING,
    CharsTokenCounter,
    PromptAssembler,
    truncate_text_to_tokens,
)


class TutorState(str, Enum):
    ONBOARDING = "ONBOARDING"
    TEACH_STEP = "TEACH_STEP"
    MICRO_CHECK = "MICRO_CHECK"
    INTERRUPT_QA = "INTERRUPT_QA"
    RECAP = "RECAP"


@dataclass(frozen=True)
class StateEvent:
    """Event emitted whenever the FSM transitions between states."""

    event_type: str = "STATE_CHANGE"
    from_state: str = ""
    to_state: str = ""
    turn_id: int = 0
    current_node_path: str = ""
    reason: str = ""


@dataclass
class TutorSession:
    """In-memory representation of a tutor session backed by Postgres."""

    id: UUID
    course_id: UUID
    active_chapter_path: str
    current_node_path: str
    fsm_state: str
    active_turn_id: int
    preferences: dict[str, Any] = field(default_factory=dict)
    resume_stack: list[dict[str, Any]] = field(default_factory=list)
    board_snapshot: dict[str, Any] = field(default_factory=dict)
    fsm_data: dict[str, Any] = field(default_factory=dict)
    snapshot: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


CONFIRMATION_PATTERNS = [
    r"\bgot it\b",
    r"\bi get it\b",
    r"\bunderstood\b",
    r"\bmakes sense\b",
    r"\bthat makes sense\b",
    r"\bi understand\b",
    r"\bclear now\b",
    r"\ball clear\b",
    r"\bthank you\b",
    r"\bthanks\b",
    r"\bok got it\b",
    r"\bokay got it\b",
    r"\bcrystal clear\b",
]


def is_confirmation_intent(text: str) -> bool:
    """Detect if student is confirming understanding rather than asking a follow-up."""
    cleaned = text.strip().lower()
    for pattern in CONFIRMATION_PATTERNS:
        if re.search(pattern, cleaned):
            return True
    return False


def _semantic_board_summary(board_snapshot: dict[str, Any]) -> str:
    """Extract only semantic labels and LaTeX strings from a board snapshot.

    Per PATTERNS.md Invariant 7: "semantic board summary (~300 tokens, never raw
    Excalidraw JSON)".  Returns an empty string when the snapshot is empty.
    """
    if not board_snapshot:
        return ""

    counter = CharsTokenCounter()
    parts: list[str] = []

    # Extract from canonical BoardOp arrays if present
    ops = (
        board_snapshot.get("active_slide_ops")
        or board_snapshot.get("operations")
        or board_snapshot.get("ops")
        or []
    )
    for op in ops:
        if not isinstance(op, dict):
            continue
        label = op.get("label", "")
        latex = op.get("latex", "")
        payload = op.get("payload", {})
        if isinstance(payload, dict):
            label = label or payload.get("label", "")
            latex = latex or payload.get("latex", "") or payload.get("raw", "")
        if label:
            parts.append(label)
        if latex:
            parts.append(latex)

    # Fallback: extract any top-level string values (labels, latex keys)
    if not parts:
        for key, val in board_snapshot.items():
            if isinstance(val, str) and val.strip():
                parts.append(f"{key}: {val}")

    if not parts:
        return ""

    summary = "; ".join(parts)
    return truncate_text_to_tokens(
        summary, WHITEBOARD_SUMMARY_CEILING, counter, marker=""
    )


def check_scope_guardrail(
    text: str,
    current_chapter_path: str,
    all_chapters: list[dict[str, Any]],
) -> tuple[bool, dict[str, Any] | None, bool]:
    """Check if a question targets a different chapter in the syllabus.

    Returns:
        (is_out_of_scope, target_chapter_node, is_confirmed_switch)
    """
    cleaned = text.strip().lower()
    # Check explicit switch confirmation first
    switch_intent = bool(
        re.search(r"\b(switch|change|jump|move)\b.*\b(chapter|topic)\b", cleaned)
        or re.search(r"\byes\b.*\b(switch|change)\b", cleaned)
    )

    for ch in all_chapters:
        ch_path = ch.get("path", "")
        if ch_path == current_chapter_path:
            continue

        title = ch.get("title", "").lower()
        # Look for chapter path, e.g. "ch02", "ch 2", "chapter 2", or title words
        ch_num_match = re.search(r"ch0?(\d+)", ch_path)
        ch_num = ch_num_match.group(1) if ch_num_match else None

        mentions_path = ch_path.lower() in cleaned
        mentions_number = bool(
            ch_num
            and (
                f"chapter {ch_num}" in cleaned
                or f"ch {ch_num}" in cleaned
                or f"ch0{ch_num}" in cleaned
            )
        )
        mentions_title = bool(title and title in cleaned)

        if mentions_path or mentions_number or mentions_title:
            return True, ch, switch_intent

    return False, None, False


class PedagogicalFSM:
    """Explicit 5-State Pedagogical FSM driver."""

    def __init__(
        self,
        repository: ScopedLtreeRepository,
        router: LLMRouter,
        assembler: PromptAssembler | None = None,
    ) -> None:
        self.repository = repository
        self.router = router
        self.assembler = assembler if assembler is not None else PromptAssembler()

    async def get_session(self, conn: Any, session_id: UUID) -> TutorSession:
        """Fetch session from tutor_sessions table."""
        query = (
            "SELECT id, course_id, active_chapter_path::text, "
            "current_node_path::text, fsm_state, active_turn_id, "
            "preferences, resume_stack, board_snapshot, fsm_data, "
            "snapshot, created_at, updated_at FROM tutor_sessions WHERE id = %s;"
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (str(session_id),))
            row = await cur.fetchone()
            if not row:
                raise ValueError(f"TutorSession {session_id} not found")

            # Extract fields whether dict_row or tuple
            if isinstance(row, dict):
                snap = row.get("snapshot") or row.get("board_snapshot") or {}
                board_snap = row.get("board_snapshot") or snap
                return TutorSession(
                    id=UUID(str(row["id"])),
                    course_id=UUID(str(row["course_id"])),
                    active_chapter_path=row["active_chapter_path"],
                    current_node_path=row["current_node_path"],
                    fsm_state=row["fsm_state"],
                    active_turn_id=row["active_turn_id"],
                    preferences=row.get("preferences") or {},
                    resume_stack=row.get("resume_stack") or [],
                    board_snapshot=board_snap,
                    fsm_data=row.get("fsm_data") or {},
                    snapshot=snap,
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                )
            else:
                board_snap = row[8] or {}
                snap = (row[10] if len(row) > 12 else None) or board_snap
                created_at = row[11] if len(row) > 12 else row[10]
                updated_at = row[12] if len(row) > 12 else row[11]
                return TutorSession(
                    id=UUID(str(row[0])),
                    course_id=UUID(str(row[1])),
                    active_chapter_path=row[2],
                    current_node_path=row[3],
                    fsm_state=row[4],
                    active_turn_id=row[5],
                    preferences=row[6] or {},
                    resume_stack=row[7] or [],
                    board_snapshot=board_snap,
                    fsm_data=row[9] or {},
                    snapshot=snap,
                    created_at=created_at,
                    updated_at=updated_at,
                )

    async def save_session(self, conn: Any, session: TutorSession) -> None:
        """Persist current state and resume_stack into tutor_sessions."""
        snap = session.snapshot or session.board_snapshot
        query = (
            "UPDATE tutor_sessions "
            "SET fsm_state = %s, "
            "    current_node_path = %s::ltree, "
            "    active_chapter_path = %s::ltree, "
            "    active_turn_id = %s, "
            "    preferences = %s::jsonb, "
            "    resume_stack = %s::jsonb, "
            "    board_snapshot = %s::jsonb, "
            "    fsm_data = %s::jsonb, "
            "    snapshot = %s::jsonb, "
            "    updated_at = now() "
            "WHERE id = %s;"
        )
        params = (
            session.fsm_state,
            session.current_node_path,
            session.active_chapter_path,
            session.active_turn_id,
            json.dumps(session.preferences),
            json.dumps(session.resume_stack),
            json.dumps(session.board_snapshot),
            json.dumps(session.fsm_data),
            json.dumps(snap),
            str(session.id),
        )
        async with conn.cursor() as cur:
            await cur.execute(query, params)

    async def log_event(
        self,
        conn: Any,
        session_id: UUID,
        turn_id: int,
        event_type: str,
        payload: dict[str, Any],
        playout_offset_ms: int = 0,
    ) -> None:
        """Append event to session_events table."""
        query = (
            "INSERT INTO session_events "
            "(session_id, turn_id, event_type, playout_offset_ms, payload) "
            "VALUES (%s, %s, %s, %s, %s::jsonb);"
        )
        params = (
            str(session_id),
            turn_id,
            event_type,
            playout_offset_ms,
            json.dumps(payload),
        )
        async with conn.cursor() as cur:
            await cur.execute(query, params)

    async def transition(
        self,
        conn: Any,
        session: TutorSession,
        to_state: TutorState | str,
        reason: str,
        new_node_path: str | None = None,
    ) -> StateEvent:
        """Execute state transition and persist to DB."""
        from_state = session.fsm_state
        to_state_str = (
            to_state.value if isinstance(to_state, TutorState) else str(to_state)
        )

        session.fsm_state = to_state_str
        if new_node_path is not None:
            session.current_node_path = new_node_path

        session.active_turn_id += 1

        # Persist to tutor_sessions
        await self.save_session(conn, session)

        event = StateEvent(
            event_type="STATE_CHANGE",
            from_state=from_state,
            to_state=to_state_str,
            turn_id=session.active_turn_id,
            current_node_path=session.current_node_path,
            reason=reason,
        )

        # Log transition event in session_events
        await self.log_event(
            conn,
            session.id,
            session.active_turn_id,
            "STATE_CHANGE",
            {
                "from_state": from_state,
                "to_state": to_state_str,
                "current_node_path": session.current_node_path,
                "reason": reason,
            },
        )
        return event

    async def get_chapter_subtopics(
        self, conn: Any, course_id: UUID, chapter_path: str
    ) -> list[dict[str, Any]]:
        """Fetch all teachable subtopics/topics strictly within active chapter."""
        nodes = await self.repository.query_syllabus_nodes(course_id, chapter_path)
        # Filter for topics/subtopics (skip root chapter node itself)
        subtopics = [n for n in nodes if str(n.get("path")) != chapter_path]
        subtopics.sort(key=lambda x: int(x.get("order_index", 0)))
        return subtopics

    async def get_all_chapters(
        self, conn: Any, course_id: UUID
    ) -> list[dict[str, Any]]:
        """Fetch all chapter nodes for the course."""
        query = (
            "SELECT id, course_id, path::text AS path, node_type, order_index, "
            "title, summary, mastery_status "
            "FROM syllabus_nodes "
            "WHERE course_id = %s AND (node_type = 'chapter' OR nlevel(path) = 1) "
            "ORDER BY order_index ASC;"
        )
        async with conn.cursor() as cur:
            await cur.execute(query, (str(course_id),))
            rows = await cur.fetchall()
            return cast(list[dict[str, Any]], rows)

    async def _emit_parsed_event(
        self,
        conn: Any,
        session: TutorSession,
        event: ParsedEvent,
    ) -> ParsedEvent:
        """Record and return parsed event."""
        payload: dict[str, Any] = {}
        event_name = event.__class__.__name__

        if isinstance(event, SayEvent):
            payload = {"text": event.text}
        elif isinstance(event, LatexEvent):
            payload = {"latex": event.latex}
        elif isinstance(event, PlotEvent):
            payload = {"spec": event.spec}
        elif isinstance(event, DiagramEvent):
            payload = {"spec": event.spec}
        elif isinstance(event, ClearEvent):
            payload = {}
        elif isinstance(event, CtrlEvent):
            payload = event.payload

        await self.log_event(
            conn,
            session.id,
            session.active_turn_id,
            event_name,
            payload,
        )
        return event

    async def handle_turn(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None = None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Dispatch turn processing with turn-boundary snapshot persistence."""
        snap = session.snapshot or session.board_snapshot or {}
        active_slide_ops: list[dict[str, Any]] = list(snap.get("active_slide_ops", []))
        slides: list[dict[str, Any]] = list(snap.get("slides", []))
        active_slide_index: int = int(snap.get("active_slide_index", len(slides)))

        # Log student input if present
        if student_text:
            await self.log_event(
                conn,
                session.id,
                session.active_turn_id,
                "STUDENT_MESSAGE",
                {"text": student_text},
            )

        async def _run_turn() -> AsyncIterator[ParsedEvent | StateEvent]:
            if session.fsm_state == TutorState.ONBOARDING.value:
                async for ev in self._handle_onboarding(conn, session, student_text):
                    yield ev
            elif session.fsm_state == TutorState.TEACH_STEP.value:
                async for ev in self._handle_teach_step(conn, session, student_text):
                    yield ev
            elif session.fsm_state == TutorState.MICRO_CHECK.value:
                async for ev in self._handle_micro_check(conn, session, student_text):
                    yield ev
            elif session.fsm_state == TutorState.INTERRUPT_QA.value:
                async for ev in self._handle_interrupt_qa(conn, session, student_text):
                    yield ev
            elif session.fsm_state == TutorState.RECAP.value:
                async for ev in self._handle_recap(conn, session, student_text):
                    yield ev

        async for ev in _run_turn():
            if isinstance(ev, LatexEvent):
                op = {
                    "op_id": f"op_{session.active_turn_id}_{len(active_slide_ops) + 1}",
                    "op_type": "latex",
                    "playout_offset_ms": 0,
                    "payload": {
                        "latex": ev.latex,
                        "raw": ev.latex,
                        "label": f"Formula {len(active_slide_ops) + 1}",
                    },
                    "placement": {"zone": "derivation"},
                }
                active_slide_ops.append(op)
            elif isinstance(ev, PlotEvent):
                op = {
                    "op_id": f"op_{session.active_turn_id}_{len(active_slide_ops) + 1}",
                    "op_type": "plot",
                    "playout_offset_ms": 0,
                    "payload": {
                        "spec": ev.spec,
                        "label": f"Plot {len(active_slide_ops) + 1}",
                    },
                    "placement": {"zone": "visual"},
                }
                active_slide_ops.append(op)
            elif isinstance(ev, DiagramEvent):
                op = {
                    "op_id": f"op_{session.active_turn_id}_{len(active_slide_ops) + 1}",
                    "op_type": "diagram",
                    "playout_offset_ms": 0,
                    "payload": {
                        "spec": ev.spec,
                        "label": f"Diagram {len(active_slide_ops) + 1}",
                    },
                    "placement": {"zone": "visual"},
                }
                active_slide_ops.append(op)
            elif isinstance(ev, ClearEvent):
                slides.append({
                    "slide_number": len(slides) + 1,
                    "ops": list(active_slide_ops),
                })
                active_slide_ops.clear()
                active_slide_index = len(slides)

            yield ev

        # AT TURN BOUNDARY: Save compact snapshot after turn finishes
        compact_snapshot = {
            "active_slide_index": active_slide_index,
            "active_slide_ops": active_slide_ops,
            "slides": slides,
            "active_chapter_path": session.active_chapter_path,
            "current_node_path": session.current_node_path,
            "fsm_state": session.fsm_state,
            "active_turn_id": session.active_turn_id,
            "subtopic_cursor": session.current_node_path,
        }
        session.snapshot = compact_snapshot
        session.board_snapshot = compact_snapshot
        await self.save_session(conn, session)

    async def _handle_onboarding(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Collect baseline on first turn, then advance to TEACH_STEP."""
        if not student_text:
            # First greeting
            greeting = SayEvent(
                text=(
                    "Welcome to your tutoring session! Before we begin, have you "
                    "studied this material before, or is this brand new?"
                )
            )
            yield await self._emit_parsed_event(conn, session, greeting)
            return

        # Baseline collected
        session.preferences["baseline"] = student_text
        subtopics = await self.get_chapter_subtopics(
            conn, session.course_id, session.active_chapter_path
        )
        first_subtopic_path = (
            subtopics[0]["path"] if subtopics else session.active_chapter_path
        )

        state_ev = await self.transition(
            conn,
            session,
            to_state=TutorState.TEACH_STEP,
            new_node_path=first_subtopic_path,
            reason="baseline_collected",
        )
        yield state_ev

        # Begin teaching first subtopic
        async for ev in self._teach_subtopic(conn, session):
            yield ev

    async def _handle_teach_step(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Handle teach step or mid-step student interruption."""
        if not student_text:
            # Continue subtopic teaching
            async for ev in self._teach_subtopic(conn, session):
                yield ev
            return

        # Student spoke during TEACH_STEP -> INTERRUPT!
        all_chapters = await self.get_all_chapters(conn, session.course_id)
        is_oos, target_ch, is_switch = check_scope_guardrail(
            student_text, session.active_chapter_path, all_chapters
        )

        if is_oos and target_ch is not None:
            if is_switch:
                target_path = str(target_ch["path"])
                target_title = str(target_ch.get("title", target_path))
                session.active_chapter_path = target_path
                session.resume_stack.clear()
                subtopics = await self.get_chapter_subtopics(
                    conn, session.course_id, target_path
                )
                next_path = subtopics[0]["path"] if subtopics else target_path

                yield await self._emit_parsed_event(
                    conn,
                    session,
                    SayEvent(text=f"Switching now to Chapter: {target_title}."),
                )
                state_ev = await self.transition(
                    conn,
                    session,
                    to_state=TutorState.TEACH_STEP,
                    new_node_path=next_path,
                    reason="explicit_chapter_switch",
                )
                yield state_ev
                async for ev in self._teach_subtopic(conn, session):
                    yield ev
                return
            else:
                # Politely defer and stay in TEACH_STEP
                other_title = str(
                    target_ch.get("title", target_ch.get("path", "the next chapter"))
                )
                deferral = SayEvent(
                    text=(
                        f"That connects to {other_title}. We will cover that "
                        "later. Let's finish our current topic first."
                    )
                )
                yield await self._emit_parsed_event(conn, session, deferral)
                return

        # Mid-step question inside current chapter
        # Push pending items & paused subpoint onto resume_stack
        pending_items = session.fsm_data.get("pending_items", [])
        paused_subpoint = (
            session.fsm_data.get("active_subpoint_name") or session.current_node_path
        )
        stack_frame: dict[str, Any] = {
            "node_path": session.current_node_path,
            "subpoint_name": paused_subpoint,
            "pending_items": pending_items,
            "turn_id": session.active_turn_id,
            "question": student_text,
            "clarifications": [],
        }
        session.resume_stack.append(stack_frame)

        state_ev = await self.transition(
            conn,
            session,
            to_state=TutorState.INTERRUPT_QA,
            reason="student_interrupted_mid_step",
        )
        yield state_ev

        # Answer question using scoped RAG for active_chapter_path
        async for ev in self._answer_question_scoped(conn, session, student_text):
            if isinstance(ev, SayEvent) and session.resume_stack:
                session.resume_stack[-1].setdefault("clarifications", []).append(
                    ev.text
                )
            yield ev

    async def _handle_interrupt_qa(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Handle Q&A inside INTERRUPT_QA until student confirms understanding."""
        if not student_text:
            return

        all_chapters = await self.get_all_chapters(conn, session.course_id)
        is_oos, target_ch, is_switch = check_scope_guardrail(
            student_text, session.active_chapter_path, all_chapters
        )

        if is_oos and target_ch is not None:
            if is_switch:
                target_path = str(target_ch["path"])
                target_title = str(target_ch.get("title", target_path))
                session.active_chapter_path = target_path
                session.resume_stack.clear()
                subtopics = await self.get_chapter_subtopics(
                    conn, session.course_id, target_path
                )
                next_path = subtopics[0]["path"] if subtopics else target_path

                yield await self._emit_parsed_event(
                    conn,
                    session,
                    SayEvent(text=f"Switching now to Chapter: {target_title}."),
                )
                state_ev = await self.transition(
                    conn,
                    session,
                    to_state=TutorState.TEACH_STEP,
                    new_node_path=next_path,
                    reason="explicit_chapter_switch",
                )
                yield state_ev
                async for ev in self._teach_subtopic(conn, session):
                    yield ev
                return
            else:
                # Deferral: stay in INTERRUPT_QA
                other_title = str(
                    target_ch.get("title", target_ch.get("path", "the next chapter"))
                )
                deferral = SayEvent(
                    text=(
                        f"That connects to {other_title}. We will cover that "
                        "later. Let's finish our current topic first."
                    )
                )
                yield await self._emit_parsed_event(conn, session, deferral)
                return

        # Check if student confirms understanding
        if is_confirmation_intent(student_text):
            frame = session.resume_stack.pop() if session.resume_stack else {}
            paused_subpoint = frame.get("subpoint_name", "our lesson")
            pending_items = frame.get("pending_items", [])
            paused_node = frame.get("node_path", session.current_node_path)
            q_text = str(frame.get("question", "")).strip()
            clarifications_list = frame.get("clarifications", [])
            clarification_text = " ".join(clarifications_list).strip()

            clarification_msg = (
                clarification_text
                or "Cleared during interactive Q&A discussion."
            )
            # Record cleared misconception in session_events
            await self.log_event(
                conn,
                session.id,
                session.active_turn_id,
                "MISCONCEPTION_CLEARED",
                {
                    "question": q_text or "Concept clarification during interrupt",
                    "clarification": clarification_msg,
                    "subtopic_path": paused_node,
                    "subpoint_name": paused_subpoint,
                    "turn_id": session.active_turn_id,
                },
            )

            bridging_ev = SayEvent(
                text=f"Great! Let's return to where we left off on {paused_subpoint}."
            )
            yield await self._emit_parsed_event(conn, session, bridging_ev)

            state_ev = await self.transition(
                conn,
                session,
                to_state=TutorState.TEACH_STEP,
                new_node_path=paused_node,
                reason="interrupt_resolved",
            )
            yield state_ev

            # Resume pending items
            has_micro_check = False
            for item in pending_items:
                if isinstance(item, dict):
                    op_type = item.get("type", "SAY")
                    if op_type == "SAY":
                        ev = SayEvent(text=sanitize_say_text(item.get("text", "")))
                    elif op_type == "LATEX":
                        ev = LatexEvent(latex=item.get("latex", ""))
                    elif op_type == "CTRL":
                        ev = CtrlEvent(payload=item.get("payload", {}))
                        if ev.payload.get("action") == "micro_check":
                            has_micro_check = True
                    else:
                        ev = SayEvent(text=str(item))
                else:
                    ev = item
                    if (
                        isinstance(ev, CtrlEvent)
                        and ev.payload.get("action") == "micro_check"
                    ):
                        has_micro_check = True

                yield await self._emit_parsed_event(conn, session, ev)

            # Clear pending items now that they've been delivered
            session.fsm_data["pending_items"] = []
            await self.save_session(conn, session)

            if has_micro_check:
                mc_ev = await self.transition(
                    conn,
                    session,
                    to_state=TutorState.MICRO_CHECK,
                    reason="micro_check_started",
                )
                yield mc_ev
            return

        # Follow-up question: answer with scoped RAG
        if session.resume_stack:
            session.resume_stack[-1].setdefault("clarifications", [])
        async for ev in self._answer_question_scoped(conn, session, student_text):
            if isinstance(ev, SayEvent) and session.resume_stack:
                session.resume_stack[-1].setdefault("clarifications", []).append(
                    ev.text
                )
            yield ev

    async def _handle_micro_check(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Evaluate student micro-check answer with small router call."""
        if not student_text:
            return

        # Evaluate verdict with small router call
        eval_prompt = [
            ChatMessage(
                role="system",
                content=(
                    "You are a strict grading evaluator for a micro-check question.\n"
                    "Evaluate the student's answer.\n"
                    "Output verdict strictly: CORRECT, INCORRECT, or CONFUSED.\n"
                    "On line 2, provide a brief feedback explanation."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Student answer to micro-check: {student_text}",
            ),
        ]

        full_response = ""
        async for delta in self.router.stream(eval_prompt, size_hint="small"):
            full_response += delta.text

        tokens = re.findall(r"[A-Z]+", full_response.strip().split("\n")[0].upper())
        first_token = tokens[0] if tokens else ""
        if first_token == "CORRECT":
            verdict = "correct"
        elif first_token == "CONFUSED":
            verdict = "confused"
        else:
            verdict = "incorrect"

        if verdict == "correct":
            # Provide positive feedback
            feedback = SayEvent(text="Spot on! That is correct.")
            yield await self._emit_parsed_event(conn, session, feedback)

            # Record subtopic mastery
            mastery = session.fsm_data.setdefault("mastery", {})
            mastery[session.current_node_path] = True

            # Advance to next subtopic or RECAP
            subtopics = await self.get_chapter_subtopics(
                conn, session.course_id, session.active_chapter_path
            )
            current_paths = [s["path"] for s in subtopics]
            current_idx = (
                current_paths.index(session.current_node_path)
                if session.current_node_path in current_paths
                else -1
            )

            if current_idx >= 0 and current_idx + 1 < len(subtopics):
                next_subtopic = subtopics[current_idx + 1]
                session.fsm_data["remedial_analogy"] = False
                state_ev = await self.transition(
                    conn,
                    session,
                    to_state=TutorState.TEACH_STEP,
                    new_node_path=next_subtopic["path"],
                    reason="micro_check_passed_advance",
                )
                yield state_ev
                async for ev in self._teach_subtopic(conn, session):
                    yield ev
            else:
                # Chapter complete!
                state_ev = await self.transition(
                    conn,
                    session,
                    to_state=TutorState.RECAP,
                    reason="chapter_completed",
                )
                yield state_ev
                async for ev in self._recap_chapter(conn, session):
                    yield ev

        else:
            # Incorrect or confused -> repeat SAME subtopic with remedial_analogy
            feedback = SayEvent(
                text=(
                    "Not quite. Let's revisit this concept with a different "
                    "perspective and analogy."
                )
            )
            yield await self._emit_parsed_event(conn, session, feedback)

            session.fsm_data["remedial_analogy"] = True
            state_ev = await self.transition(
                conn,
                session,
                to_state=TutorState.TEACH_STEP,
                new_node_path=session.current_node_path,  # order_index does not advance
                reason="micro_check_failed_remedial",
            )
            yield state_ev
            async for ev in self._teach_subtopic(conn, session):
                yield ev

    async def _handle_recap(
        self,
        conn: Any,
        session: TutorSession,
        student_text: str | None,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Handle interactions in RECAP state."""
        closing = SayEvent(
            text="Chapter completed! You have finished this chapter's learning goals."
        )
        yield await self._emit_parsed_event(conn, session, closing)

    async def _teach_subtopic(
        self,
        conn: Any,
        session: TutorSession,
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        """Assemble subtopic prompt, stream through router, and yield parsed events."""
        # 1. Fetch subtopic node & RAG chunks under current_node_path
        nodes = await self.repository.query_syllabus_nodes(
            session.course_id, session.current_node_path
        )
        current_node = nodes[0] if nodes else {}
        title = current_node.get("title", "")
        summary = current_node.get("summary", "")

        chunks = await self.repository.query_document_chunks(
            session.course_id,
            session.current_node_path,
            limit=3,
        )

        remedial = bool(session.fsm_data.get("remedial_analogy", False))
        session.fsm_data["active_subpoint_name"] = title

        assembled = self.assembler.assemble(
            subtopic_title=title,
            subtopic_brief=summary,
            rag_chunks=chunks,
            whiteboard_summary=_semantic_board_summary(session.board_snapshot),
            remedial_analogy=remedial,
        )

        parser = LineStreamParser()
        has_micro_check = False

        async for delta in self.router.stream(assembled.messages, size_hint="large"):
            events = parser.feed(delta.text)
            for ev in events:
                if (
                    isinstance(ev, CtrlEvent)
                    and ev.payload.get("action") == "micro_check"
                ):
                    has_micro_check = True
                yield await self._emit_parsed_event(conn, session, ev)

        flushed = parser.flush()
        for ev in flushed:
            if isinstance(ev, CtrlEvent) and ev.payload.get("action") == "micro_check":
                has_micro_check = True
            yield await self._emit_parsed_event(conn, session, ev)

        if has_micro_check:
            mc_ev = await self.transition(
                conn,
                session,
                to_state=TutorState.MICRO_CHECK,
                reason="micro_check_started",
            )
            yield mc_ev

    async def _answer_question_scoped(
        self,
        conn: Any,
        session: TutorSession,
        question: str,
    ) -> AsyncIterator[ParsedEvent]:
        """Answer question with scoped RAG for CURRENT chapter only."""
        chunks = await self.repository.query_document_chunks(
            session.course_id,
            session.active_chapter_path,
            search_query=question,
            limit=3,
        )

        assembled = self.assembler.assemble(
            subtopic_title=f"Q&A on Chapter {session.active_chapter_path}",
            subtopic_brief=f"Student Question: {question}",
            rag_chunks=chunks,
            whiteboard_summary=_semantic_board_summary(session.board_snapshot),
            conversation_turns=[ChatMessage(role="user", content=question)],
            extra_instructions=(
                "Answer the student's question clearly. Math ONLY in LATEX: lines."
            ),
        )

        parser = LineStreamParser()
        async for delta in self.router.stream(assembled.messages, size_hint="small"):
            events = parser.feed(delta.text)
            for ev in events:
                yield await self._emit_parsed_event(conn, session, ev)

        for ev in parser.flush():
            yield await self._emit_parsed_event(conn, session, ev)

    async def _recap_chapter(
        self,
        conn: Any,
        session: TutorSession,
    ) -> AsyncIterator[ParsedEvent]:
        """Deliver chapter recap."""
        prompt = [
            ChatMessage(
                role="system",
                content=(
                    "You are an AI Video Tutor concluding a chapter.\n"
                    "Provide a warm recap of the key formulas in this chapter.\n"
                    "Math ONLY in LATEX: lines. Natural spoken text in SAY: lines."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Summarize Chapter {session.active_chapter_path} "
                    "and congratulate the student on completion."
                ),
            ),
        ]

        parser = LineStreamParser()
        async for delta in self.router.stream(prompt, size_hint="small"):
            events = parser.feed(delta.text)
            for ev in events:
                yield await self._emit_parsed_event(conn, session, ev)

        for ev in parser.flush():
            yield await self._emit_parsed_event(conn, session, ev)

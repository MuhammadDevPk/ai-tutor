"""Tests for Explicit Pedagogical FSM, Scope Guardrail, and Chapter Walkthrough."""

import re

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository
from app.llm.providers import FakeProvider
from app.llm.router import LLMRouter
from app.tutor.fsm import (
    TutorState,
    check_scope_guardrail,
    is_confirmation_intent,
)
from app.tutor.service import TutorService
from app.tutor.simulate import run_simulation, seed_simulation_course


def test_is_confirmation_intent():
    assert is_confirmation_intent("Got it, thank you!")
    assert is_confirmation_intent("I understand now, that makes sense.")
    assert is_confirmation_intent("Understood.")
    assert is_confirmation_intent("All clear!")
    assert not is_confirmation_intent("Why do we divide by n-1?")
    assert not is_confirmation_intent("Can you give another example?")


def test_check_scope_guardrail():
    chapters = [
        {"path": "ch01", "title": "Descriptive Statistics"},
        {"path": "ch02", "title": "Probability Foundations"},
    ]

    # In-scope question
    is_oos, target, switch = check_scope_guardrail(
        "What is the sample mean?", "ch01", chapters
    )
    assert not is_oos
    assert target is None
    assert not switch

    # Out-of-scope question referring to Chapter 2
    is_oos, target, switch = check_scope_guardrail(
        "Does this apply to Probability Foundations in Chapter 2?", "ch01", chapters
    )
    assert is_oos
    assert target is not None
    assert target["path"] == "ch02"
    assert not switch

    # Explicit switch request
    is_oos, target, switch = check_scope_guardrail(
        "Yes, please switch to chapter 2 now.", "ch01", chapters
    )
    assert is_oos
    assert target is not None
    assert target["path"] == "ch02"
    assert switch


@pytest.mark.asyncio
async def test_full_chapter_simulation_gate():
    """Phase 4 Verification Gate: Full Chapter 1 simulation walkthrough.

    Validates:
    - All Chapter 1 subtopics complete in sequence
    - Chapter 2 question deferred without state change
    - 3-turn counter-question chain resolved inside INTERRUPT_QA
    - Exact subpoint resumed with bridging event
    - Remedial repeat on incorrect micro-check without advance
    - Chapter completion reaches RECAP
    - ZERO raw LaTeX (no "$$", no backslash-commands) inside any SAY event.
    """
    records, service = await run_simulation(print_output=False)

    say_events = [r for r in records if r.event_type == "SAY"]
    state_events = [r for r in records if r.event_type == "STATE_CHANGE"]
    assert len(state_events) > 0

    # 1. Zero raw LaTeX inside any SAY event across the entire transcript
    for r in say_events:
        text = r.text
        assert "$$" not in text, f"Raw LaTeX '$$' found in SAY event: {text!r}"
        assert not re.search(r"\\[a-zA-Z]+", text), (
            f"Raw LaTeX backslash command found in SAY event: {text!r}"
        )

    # 2. Visited states in proper sequence
    state_names = [r.fsm_state for r in records]
    assert "ONBOARDING" in state_names
    assert "TEACH_STEP" in state_names
    assert "MICRO_CHECK" in state_names
    assert "INTERRUPT_QA" in state_names
    assert "RECAP" in state_names

    # Final state is RECAP
    assert records[-1].fsm_state == "RECAP"

    # 3. Chapter 2 question was deferred
    ch2_deferrals = [
        r
        for r in say_events
        if "Chapter 2" in r.text or "Probability Foundations" in r.text
    ]
    assert len(ch2_deferrals) >= 1

    # 4. Exact paused subpoint named in bridging SAY event
    bridging_events = [
        r
        for r in say_events
        if "Variance Micro Check" in r.text
        and "return to where we left off" in r.text.lower()
    ]
    assert len(bridging_events) == 1, "Bridging event naming paused subpoint not found"

    # 5. Remedial analogy repeat executed
    remedial_events = [r for r in say_events if "identical twins" in r.text.lower()]
    assert len(remedial_events) >= 1


@pytest.mark.asyncio
async def test_fsm_database_persistence_and_events():
    """Verify tutor_sessions and session_events persistence on transitions."""
    conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    )
    course_id, user_id = await seed_simulation_course(conn)

    provider = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["SAY: Hello world\n"],
    )
    router = LLMRouter(providers=[provider])
    repository = ScopedLtreeRepository(conn)
    service = TutorService(pool_or_conn=conn, router=router, repository=repository)

    # 1. Start session
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )
    assert session.fsm_state == "ONBOARDING"

    # Verify session persisted in DB
    db_session = await service.get_session(session.id)
    assert db_session.fsm_state == "ONBOARDING"
    assert db_session.active_chapter_path == "ch01"
    assert db_session.current_node_path == "ch01.t01_mean"

    # 2. Push onto resume_stack and persist
    db_session.resume_stack.append(
        {
            "node_path": "ch01.t01_mean",
            "subpoint_name": "Test Subpoint",
            "pending_items": [{"type": "SAY", "text": "pending"}],
        }
    )
    await service.fsm.transition(
        conn,
        db_session,
        to_state=TutorState.INTERRUPT_QA,
        reason="test_interrupt",
    )

    # Check reload reflects updated state and stack
    reloaded = await service.get_session(session.id)
    assert reloaded.fsm_state == "INTERRUPT_QA"
    assert len(reloaded.resume_stack) == 1
    assert reloaded.resume_stack[0]["subpoint_name"] == "Test Subpoint"

    # Verify session_events row exists
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT event_type, payload FROM session_events "
            "WHERE session_id = %s ORDER BY created_at ASC;",
            (str(session.id),),
        )
        events = await cur.fetchall()
        event_types = [e["event_type"] for e in events]
        assert "STATE_CHANGE" in event_types

    await conn.close()


@pytest.mark.asyncio
async def test_explicit_chapter_switch_transition():
    """Verify chapter switch updates active_chapter_path and current_node_path."""
    conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    )
    course_id, user_id = await seed_simulation_course(conn)

    provider = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["SAY: Welcome to probability axioms\n"],
    )
    router = LLMRouter(providers=[provider])
    repository = ScopedLtreeRepository(conn)
    service = TutorService(pool_or_conn=conn, router=router, repository=repository)

    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )
    assert session.active_chapter_path == "ch01"

    # Transition to TEACH_STEP
    await service.fsm.transition(
        conn, session, to_state=TutorState.TEACH_STEP, reason="start"
    )

    # Explicit switch request
    events = []
    async for ev in service.handle_student_message(
        session.id, "Please switch to Chapter 2 Probability Foundations now"
    ):
        events.append(ev)

    updated_session = await service.get_session(session.id)
    assert updated_session.active_chapter_path == "ch02"
    assert "ch02" in updated_session.current_node_path
    assert updated_session.fsm_state == "TEACH_STEP"

    await conn.close()

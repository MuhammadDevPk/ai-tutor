"""Tests for Phase 9: Session Persistence, Interactive Replay & Exam Study Exports.

Verifies:
1. Snapshot save/restore round-trip with canonical BoardOps and ltree lock.
2. Adversarial mid-turn refresh: partial turn does not corrupt snapshot.
3. Interactive timeline replay: sequential event application & scrub past QA.
4. Clean raw LaTeX copy from replay board elements.
5. Adversarial empty session export: zero crashes, valid fallback markdown.
6. Study cheat sheet export: formula accuracy and cleared misconceptions.
7. Read-only Course Mastery aggregation: chapter completion % and weak subtopics.
8. API endpoints for reload recovery, replay, cheat sheet, and mastery.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.rows import dict_row

from app.auth import create_access_token
from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository
from app.exports.cheat_sheet import _clean_latex, generate_cheat_sheet
from app.exports.mastery import get_course_mastery
from app.llm.providers import FakeProvider
from app.llm.router import LLMRouter
from app.main import app
from app.routers.sessions import _row_to_event
from app.tutor.service import TutorService
from app.tutor.simulate import seed_simulation_course


@pytest.fixture
async def db_conn():
    conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    )
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_snapshot_save_restore_round_trip(db_conn):
    """Test 1: Turn-boundary snapshot persists canonical BoardOps, FSM cursor,

    and restores exactly upon reload.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    provider = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=[
            "SAY: Welcome to Descriptive Statistics.\n",
            "LATEX: \\bar{x} = \\frac{1}{n} \\sum_{i=1}^n x_i\n",
            'CTRL: {"action": "micro_check"}\n',
        ],
    )
    router = LLMRouter(providers=[provider])
    repository = ScopedLtreeRepository(db_conn)
    service = TutorService(
        pool_or_conn=db_conn,
        router=router,
        repository=repository,
    )

    # 1. Start session (ONBOARDING)
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )
    assert session.fsm_state == "ONBOARDING"
    assert session.active_chapter_path == "ch01"

    # 2. Turn 1: Student responds with baseline -> transition to TEACH_STEP & stream
    events = [
        ev
        async for ev in service.handle_student_message(
            session.id, "I have basic algebra knowledge."
        )
    ]
    assert len(events) > 0

    # 3. Simulate browser refresh / reopening in-progress session:
    # Fetch session fresh from the database via repository / get_session
    restored = await service.get_session(session.id)
    assert restored.id == session.id
    assert restored.active_chapter_path == "ch01"
    assert restored.fsm_state == "MICRO_CHECK"
    assert restored.current_node_path == "ch01.t01_mean"

    # Verify snapshot content
    snap = restored.snapshot or restored.board_snapshot
    assert snap is not None
    assert "active_slide_ops" in snap
    assert len(snap["active_slide_ops"]) == 1

    board_op = snap["active_slide_ops"][0]
    assert board_op["op_type"] == "latex"
    assert "\\bar{x}" in board_op["payload"]["latex"]

    # Verify NO heavy SVG blobs stored in Postgres JSONB
    raw_json = json.dumps(snap)
    assert "<svg" not in raw_json
    assert "data:image/svg+xml" not in raw_json


@pytest.mark.asyncio
async def test_adversarial_refresh_mid_turn_does_not_corrupt_restore(db_conn):
    """Test 2: Adversarial case: mid-turn cancellation/refresh must NOT update

    or corrupt the snapshot in Postgres. It stays at the last turn boundary.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    # First turn finishes cleanly with equation 1
    provider1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=[
            "SAY: Here is the mean formula.\n",
            "LATEX: \\mu = \\frac{\\sum x}{N}\n",
        ],
    )
    router1 = LLMRouter(providers=[provider1])
    service1 = TutorService(
        pool_or_conn=db_conn,
        router=router1,
        repository=ScopedLtreeRepository(db_conn),
    )

    session = await service1.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )
    # Complete turn 1
    async for _ in service1.handle_student_message(session.id, "Hello"):
        pass

    # Record valid turn 1 snapshot
    turn1_session = await service1.get_session(session.id)
    snap1 = turn1_session.snapshot or turn1_session.board_snapshot
    ops_turn1 = snap1.get("active_slide_ops", [])
    assert len(ops_turn1) == 1
    assert "\\mu" in ops_turn1[0]["payload"]["latex"]

    # Turn 2: LLM streams partial delta, but client disconnects mid-turn
    provider2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=[
            "SAY: Next equation.\n",
            "LATEX: \\text{CORRUPT_PARTIAL_EQUATION}\n",
            "SAY: Never finished...\n",
        ],
    )
    router2 = LLMRouter(providers=[provider2])
    service2 = TutorService(
        pool_or_conn=db_conn,
        router=router2,
        repository=ScopedLtreeRepository(db_conn),
    )

    # Simulate client closing generator after 1st event (mid-turn abort)
    turn_generator = service2.handle_student_message(session.id, "Continue")
    async for ev in turn_generator:
        # Break immediately on first event to simulate mid-turn abort
        break
    await turn_generator.aclose()

    # Now reload session from DB: must still reflect strictly Turn 1 snapshot!
    reloaded = await service2.get_session(session.id)
    snap_reloaded = reloaded.snapshot or reloaded.board_snapshot
    ops_reloaded = snap_reloaded.get("active_slide_ops", [])

    # Turn 2 partial equation was NOT committed to the turn-boundary snapshot
    assert len(ops_reloaded) == 1
    assert "CORRUPT_PARTIAL_EQUATION" not in json.dumps(ops_reloaded)
    assert "\\mu" in ops_reloaded[0]["payload"]["latex"]


@pytest.mark.asyncio
async def test_replay_event_application_and_scrubbing_past_interrupt_qa(db_conn):
    """Test 3: Timeline replayer reconstructs board state across events,

    handles CLEAR ops, and scrubs past INTERRUPT_QA loops cleanly.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    service = TutorService(
        pool_or_conn=db_conn,
        router=LLMRouter(providers=[FakeProvider(name="f", model="m", deltas=[])]),
        repository=ScopedLtreeRepository(db_conn),
    )
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )

    # Manually append structured sequence of events for a full chapter
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=1,
        event_type="STATE_CHANGE",
        payload={
            "from_state": "ONBOARDING",
            "to_state": "TEACH_STEP",
            "current_node_path": "ch01.t01.s01",
        },
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=1,
        event_type="LatexEvent",
        payload={
            "latex": "\\bar{x} = \\frac{1}{n} \\sum x_i",
            "label": "Sample Mean",
        },
    )

    # Turn 2: Clear slide + formula 2
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=2,
        event_type="ClearEvent",
        payload={},
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=2,
        event_type="LatexEvent",
        payload={
            "latex": "s^2 = \\frac{1}{n-1}\\sum (x_i - \\bar{x})^2",
            "label": "Sample Variance",
        },
    )

    # Turn 3: Student interrupt -> INTERRUPT_QA
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=3,
        event_type="STUDENT_MESSAGE",
        payload={"text": "Why do we divide by n-1 instead of n?"},
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=3,
        event_type="STATE_CHANGE",
        payload={
            "from_state": "TEACH_STEP",
            "to_state": "INTERRUPT_QA",
            "current_node_path": "ch01.t01.s02",
        },
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=3,
        event_type="SayEvent",
        payload={"text": "Bessel's correction accounts for degrees of freedom."},
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=3,
        event_type="LatexEvent",
        payload={
            "latex": "E[s^2] = \\sigma^2",
            "label": "Unbiased Estimator Proof",
        },
    )

    # Turn 4: Student confirms -> interrupt resolved
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=4,
        event_type="STUDENT_MESSAGE",
        payload={"text": "Got it, that makes sense!"},
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=4,
        event_type="MISCONCEPTION_CLEARED",
        payload={
            "question": "Why do we divide by n-1 instead of n?",
            "clarification": "Bessel's correction corrects bias in sample variance.",
            "subtopic_path": "ch01.t01.s02",
            "subpoint_name": "Sample Variance",
        },
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=4,
        event_type="STATE_CHANGE",
        payload={
            "from_state": "INTERRUPT_QA",
            "to_state": "TEACH_STEP",
            "reason": "interrupt_resolved",
        },
    )

    # Turn 5: Final formula on resumed lecture
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=5,
        event_type="LatexEvent",
        payload={"latex": "s = \\sqrt{s^2}", "label": "Standard Deviation"},
    )

    # Query events via API endpoint logic
    query = """
        SELECT
            id, session_id, turn_id, event_type,
            playout_offset_ms, payload, created_at
        FROM session_events
        WHERE session_id = %s
        ORDER BY turn_id ASC, created_at ASC;
    """
    async with db_conn.cursor() as cur:
        await cur.execute(query, (str(session.id),))
        all_events = await cur.fetchall()

    assert len(all_events) >= 8

    # Simulate replay scrubbing engine (pure event sourcing replay logic)
    def rebuild_board_at_step(step_idx: int):
        active_slide: list[dict] = []
        archived_slides: list[list[dict]] = []

        for ev in all_events[:step_idx]:
            ev_type = ev["event_type"]
            p = ev["payload"]
            if ev_type == "ClearEvent":
                archived_slides.append(list(active_slide))
                active_slide.clear()
            elif ev_type in ("LatexEvent", "latex") or (
                ev_type == "BOARD_OP" and p.get("op_type") == "latex"
            ):
                raw = p.get("latex") or p.get("raw") or ""
                active_slide.append({"latex": raw, "label": p.get("label", "")})

        return active_slide, archived_slides

    # Scrub point 1: after Turn 1 (before clear)
    slide_ops, archives = rebuild_board_at_step(3)
    assert len(slide_ops) == 1
    assert "\\bar{x}" in slide_ops[0]["latex"]
    assert len(archives) == 0

    # Scrub point 2: inside INTERRUPT_QA (step 9)
    slide_ops, archives = rebuild_board_at_step(9)
    # Slide 1 was archived on ClearEvent
    assert len(archives) == 1
    assert "\\bar{x}" in archives[0][0]["latex"]
    # Active slide contains Sample Variance + Q&A formula
    latex_list = [op["latex"] for op in slide_ops]
    assert any("s^2" in lx for lx in latex_list)
    assert any("E[s^2]" in lx for lx in latex_list)

    # Scrub point 3: scrubbed PAST INTERRUPT_QA to the end of the session
    slide_ops_end, archives_end = rebuild_board_at_step(len(all_events))
    assert len(archives_end) == 1
    final_latex_list = [op["latex"] for op in slide_ops_end]
    assert any("s = \\sqrt{s^2}" in lx for lx in final_latex_list)


@pytest.mark.asyncio
async def test_adversarial_empty_session_export(db_conn):
    """Test 4: Adversarial case: exporting an empty session produces clean

    fallback Markdown without throwing errors or crashing.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    service = TutorService(
        pool_or_conn=db_conn,
        router=LLMRouter(providers=[FakeProvider(name="f", model="m", deltas=[])]),
        repository=ScopedLtreeRepository(db_conn),
    )
    # Brand new session with 0 turns executed
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )

    # Generate cheat sheet
    cheat_sheet = await generate_cheat_sheet(db_conn, session.id)

    assert cheat_sheet.session_id == session.id
    assert cheat_sheet.chapter_path == "ch01"
    assert len(cheat_sheet.formulas) == 0
    assert len(cheat_sheet.misconceptions) == 0
    assert "No formulas recorded" in cheat_sheet.markdown
    assert "No misconceptions" in cheat_sheet.markdown
    assert "# Study Cheat Sheet" in cheat_sheet.markdown


@pytest.mark.asyncio
async def test_study_cheat_sheet_accuracy_with_formulas_and_misconceptions(db_conn):
    """Test 5: Cheat sheet export compiles all board formulas (raw LaTeX)

    and all cleared misconceptions into clean Markdown.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    service = TutorService(
        pool_or_conn=db_conn,
        router=LLMRouter(providers=[FakeProvider(name="f", model="m", deltas=[])]),
        repository=ScopedLtreeRepository(db_conn),
    )
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )

    # Log formulas
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=1,
        event_type="LatexEvent",
        payload={
            "latex": "\\bar{x} = \\frac{1}{n} \\sum_{i=1}^n x_i",
            "label": "Sample Mean",
        },
    )
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=2,
        event_type="LatexEvent",
        payload={
            "latex": "s^2 = \\frac{1}{n-1}\\sum (x_i - \\bar{x})^2",
            "label": "Sample Variance",
        },
    )

    # Log cleared misconception
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=3,
        event_type="MISCONCEPTION_CLEARED",
        payload={
            "question": "Why do we divide by n-1 instead of n for sample variance?",
            "clarification": "Bessel's correction accounts for degrees of freedom.",
            "subtopic_path": "ch01.t01.s02",
            "subpoint_name": "Sample Variance",
        },
    )

    # Export cheat sheet
    cheat_sheet = await generate_cheat_sheet(db_conn, session.id)

    assert len(cheat_sheet.formulas) == 2
    assert "\\bar{x}" in cheat_sheet.formulas[0].latex
    assert "s^2" in cheat_sheet.formulas[1].latex
    assert len(cheat_sheet.misconceptions) == 1
    assert "Bessel's correction" in cheat_sheet.misconceptions[0].clarification

    # Verify Markdown contents
    md = cheat_sheet.markdown
    assert "$$\n\\bar{x} = \\frac{1}{n} \\sum_{i=1}^n x_i\n$$" in md
    assert "$$\ns^2 = \\frac{1}{n-1}\\sum (x_i - \\bar{x})^2\n$$" in md
    assert "Why do we divide by n-1 instead of n for sample variance?" in md
    assert "Bessel's correction accounts for degrees of freedom." in md


@pytest.mark.asyncio
async def test_course_mastery_aggregation(db_conn):
    """Test 6: Read-only course mastery aggregation accurately computes

    chapter completion % and weak subtopics by INTERRUPT_QA frequency.
    """
    course_id, user_id = await seed_simulation_course(db_conn)

    service = TutorService(
        pool_or_conn=db_conn,
        router=LLMRouter(providers=[FakeProvider(name="f", model="m", deltas=[])]),
        repository=ScopedLtreeRepository(db_conn),
    )

    # Session 1: completed Chapter 1 (reaches RECAP)
    s1 = await service.start_session(course_id, user_id, active_chapter_path="ch01")
    s1.fsm_state = "RECAP"
    await service.fsm.save_session(db_conn, s1)

    # Log 3 interrupt loops on subtopic ch01.t01.s02 (weak subtopic)
    for _ in range(3):
        await service.fsm.log_event(
            db_conn,
            s1.id,
            turn_id=1,
            event_type="STATE_CHANGE",
            payload={
                "from_state": "TEACH_STEP",
                "to_state": "INTERRUPT_QA",
                "current_node_path": "ch01.t01.s02",
            },
        )
    await service.fsm.log_event(
        db_conn,
        s1.id,
        turn_id=1,
        event_type="MISCONCEPTION_CLEARED",
        payload={
            "question": "What is variance?",
            "clarification": "Spread of data.",
            "subtopic_path": "ch01.t01.s02",
        },
    )

    # Log 1 interrupt on subtopic ch01.t01.s01
    await service.fsm.log_event(
        db_conn,
        s1.id,
        turn_id=2,
        event_type="STATE_CHANGE",
        payload={
            "from_state": "TEACH_STEP",
            "to_state": "INTERRUPT_QA",
            "current_node_path": "ch01.t01.s01",
        },
    )

    # Session 2: Chapter 2 in progress
    s2 = await service.start_session(course_id, user_id, active_chapter_path="ch02")
    s2.fsm_state = "TEACH_STEP"
    await service.fsm.save_session(db_conn, s2)

    mastery = await get_course_mastery(db_conn, course_id)

    assert mastery.course_id == course_id
    assert mastery.total_chapters == 2
    assert mastery.completed_chapters == 1
    assert mastery.completion_percentage == 50.0

    # Chapter statuses
    status_by_path = {c.chapter_path: c.status for c in mastery.chapters}
    assert status_by_path["ch01"] == "completed"
    assert status_by_path["ch02"] == "in_progress"

    # Weak subtopics: ch01.t01.s02 must be rank #1 with most interrupts
    assert len(mastery.weak_subtopics) >= 2
    top_weak = mastery.weak_subtopics[0]
    assert top_weak.subtopic_path == "ch01.t01.s02"
    # Strict verification: exactly 3 interrupts and 1 misconception cleared
    # (verifies MISCONCEPTION_CLEARED does not double-count as an interrupt)
    assert top_weak.interrupt_count == 3
    assert top_weak.misconception_count == 1

    # Chapter QA counts: exactly 4 interrupts across ch01 (3 on s02 + 1 on s01)
    ch01_item = next(c for c in mastery.chapters if c.chapter_path == "ch01")
    assert ch01_item.interrupt_qa_count == 4


@pytest.mark.asyncio
async def test_rest_api_endpoints_reload_replay_cheat_sheet_mastery(db_conn):
    """Test 7: REST API endpoints for session reload recovery, replay events,

    cheat sheet markdown export, and course mastery dashboard.
    """
    course_id, user_id = await seed_simulation_course(db_conn)
    token = create_access_token(user_id)
    headers = {"Authorization": f"Bearer {token}"}

    service = TutorService(
        pool_or_conn=db_conn,
        router=LLMRouter(providers=[FakeProvider(name="f", model="m", deltas=[])]),
        repository=ScopedLtreeRepository(db_conn),
    )
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )

    # Add a formula and event
    await service.fsm.log_event(
        db_conn,
        session.id,
        turn_id=1,
        event_type="LatexEvent",
        payload={"latex": "\\sigma = \\sqrt{\\sigma^2}", "label": "Sigma"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /sessions/{id} for reload recovery
        resp = await client.get(f"/sessions/{session.id}", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(session.id)
        assert "snapshot" in data
        assert data["active_chapter_path"] == "ch01"

        # 2. GET /sessions/{id}/events for replay
        resp = await client.get(f"/sessions/{session.id}/events", headers=headers)
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1

        # 3. GET /sessions/{id}/replay
        resp = await client.get(f"/sessions/{session.id}/replay", headers=headers)
        assert resp.status_code == 200
        replay_data = resp.json()
        assert replay_data["session_id"] == str(session.id)
        assert len(replay_data["events"]) >= 1

        # 4. GET /sessions/{id}/cheat-sheet (JSON)
        resp = await client.get(
            f"/sessions/{session.id}/cheat-sheet", headers=headers
        )
        assert resp.status_code == 200
        cs = resp.json()
        assert cs["session_id"] == str(session.id)
        assert len(cs["formulas"]) >= 1

        # 5. GET /sessions/{id}/cheat-sheet?format=markdown
        resp = await client.get(
            f"/sessions/{session.id}/cheat-sheet?format=markdown",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "# Study Cheat Sheet" in resp.text

        # 6. GET /courses/{course_id}/mastery
        resp = await client.get(f"/courses/{course_id}/mastery", headers=headers)
        assert resp.status_code == 200
        m = resp.json()
        assert m["course_id"] == str(course_id)
        assert "chapters" in m
        assert "weak_subtopics" in m

        # 7. Authorization check: unauthorized user receives 404
        other_user_token = create_access_token(uuid4())
        other_headers = {"Authorization": f"Bearer {other_user_token}"}
        resp = await client.get(f"/sessions/{session.id}", headers=other_headers)
        assert resp.status_code == 404


def test_clean_latex_delimiter_safety():
    """Test 8: Verify _clean_latex strips redundant outer delimiters cleanly

    without corrupting compound expressions with multiple internal delimiters.
    """
    # Standard cases
    assert _clean_latex("$$x = 5$$") == "x = 5"
    assert _clean_latex("$y = 10$") == "y = 10"
    assert _clean_latex("z = 15") == "z = 15"

    # Compound cases that naive stripping corrupts
    assert _clean_latex("$$a$$ + $$b$$") == "$$a$$ + $$b$$"
    assert _clean_latex("$p$ and $q$") == "$p$ and $q$"


def test_row_to_event_handles_both_dicts_and_tuples():
    """Test 9: Verify _row_to_event validates both dict_row and tuple DB records."""
    now = datetime.now(timezone.utc)
    ev_id = uuid4()
    s_id = uuid4()

    # Tuple row
    t_row = (ev_id, s_id, 1, "LatexEvent", 150, {"latex": "x^2"}, now)
    res_t = _row_to_event(t_row)
    assert res_t.id == ev_id
    assert res_t.session_id == s_id
    assert res_t.turn_id == 1
    assert res_t.event_type == "LatexEvent"
    assert res_t.playout_offset_ms == 150
    assert res_t.payload == {"latex": "x^2"}

    # Dict row
    d_row = {
        "id": ev_id,
        "session_id": s_id,
        "turn_id": 2,
        "event_type": "SayEvent",
        "playout_offset_ms": 0,
        "payload": {"text": "Hello"},
        "created_at": now,
    }
    res_d = _row_to_event(d_row)
    assert res_d.turn_id == 2
    assert res_d.payload == {"text": "Hello"}


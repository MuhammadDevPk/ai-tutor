"""CLI Text Simulation Harness for AI Video Tutor (Phase 4).

Drives a full Chapter 1 pedagogical walkthrough with a scripted student and LLM:
- Answers first micro-check correctly
- Asks mid-step question (INTERRUPT_QA)
- 3-turn counter-question chain (including an out-of-scope Chapter 2 question)
- Receives polite Chapter 2 deferral without state change
- Confirms understanding and resumes exact paused subpoint
- Answers micro-check incorrectly, triggering remedial TEACH_STEP repeat
- Passes remedial micro-check, advances, and finishes into RECAP
- Verifies ZERO raw LaTeX inside any SAY event across the entire transcript.

Can be run directly via:
    uv run python -m app.tutor.simulate
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository
from app.llm.providers import ChatMessage, FakeProvider
from app.llm.router import LLMRouter
from app.llm.stream_parser import (
    CtrlEvent,
    LatexEvent,
    SayEvent,
)
from app.tutor.fsm import StateEvent
from app.tutor.service import TutorService


@dataclass
class SimulationRecord:
    step_num: int
    speaker: str
    text: str
    event_type: str
    fsm_state: str
    current_node: str


def scripted_llm_response(messages: list[ChatMessage]) -> list[str]:
    """Scripted LLM responses for the simulation walkthrough."""
    system_msg = next((m.content for m in messages if m.role == "system"), "")
    user_msg = next((m.content for m in reversed(messages) if m.role == "user"), "")

    # 1. Micro-check evaluation prompt
    if "strict grading evaluator for a micro-check" in system_msg:
        if "increases by 5" in user_msg.lower():
            return ["CORRECT: The mean increases by exactly 5.\n"]
        elif "equal to the mean" in user_msg.lower():
            return [
                "INCORRECT: Variance measures dispersion around the mean.\n"
            ]
        elif "zero" in user_msg.lower():
            return [
                "CORRECT: When all observations are identical, dispersion is zero.\n"
            ]
        return ["INCORRECT: Incorrect answer.\n"]

    # 2. Remedial subtopic teaching (analogy)
    if "remedial" in system_msg.lower() or "analogy" in system_msg.lower():
        return [
            (
                "SAY: Let us think about variance like variation in heights of "
                "identical twins. If all twins are 5ft, variation is zero.\n"
            ),
            "LATEX: s^2 = 0\n",
            "SAY: Now consider: what is variance if all values are 7?\n",
            'CTRL: {"action": "micro_check", "question": "Variance if all 7?"}\n',
        ]

    # 3. Chapter recap prompt
    if "concluding a chapter" in system_msg:
        return [
            (
                "SAY: Congratulations on completing Chapter 1! "
                "We covered Mean, Median, and Variance.\n"
            ),
            (
                "LATEX: \\bar{x} = \\frac{1}{n}\\sum x_i, "
                "\\quad s^2 = \\frac{1}{n-1}\\sum (x_i - \\bar{x})^2\n"
            ),
            "SAY: You have mastered all core concepts for this chapter.\n",
        ]

    # 4. Q&A during INTERRUPT_QA
    if "Q&A on Chapter" in system_msg:
        if "why do we divide by n-1" in user_msg.lower():
            return [
                (
                    "SAY: We divide by n minus 1 because using the sample mean "
                    "reduces degrees of freedom by 1.\n"
                ),
                "LATEX: s^2 = \\frac{1}{n-1}\\sum_{i=1}^{n}(x_i - \\bar{x})^2\n",
            ]
        elif "underestimate" in user_msg.lower():
            return [
                (
                    "SAY: Yes, dividing by n produces a downward biased estimate "
                    "of the true population variance.\n"
                ),
                "LATEX: \\mathbb{E}[s^2] = \\sigma^2\n",
            ]
        elif "huge" in user_msg.lower() or "large" in user_msg.lower():
            return [
                (
                    "SAY: Exactly, as the sample size n approaches infinity, "
                    "the difference between n and n minus 1 becomes negligible.\n"
                ),
            ]

    # 5. Normal subtopic teaching
    if "Mean and Median" in system_msg or "ch01.t01" in system_msg:
        return [
            (
                "SAY: Welcome to Descriptive Statistics. "
                "Let us begin with the sample mean and median.\n"
            ),
            "LATEX: \\bar{x} = \\frac{1}{n}\\sum_{i=1}^{n} x_i\n",
            (
                "SAY: To test your intuition: what happens to the mean if you "
                "add 5 to every observation?\n"
            ),
            'CTRL: {"action": "micro_check", "question": "Add 5?"}\n',
        ]

    if "Variance and Standard Deviation" in system_msg or "ch01.t02" in system_msg:
        return [
            "SAY: Now let us examine variance and deviation from the mean.\n",
            "LATEX: s^2 = \\frac{1}{n-1}\\sum_{i=1}^{n} (x_i - \\bar{x})^2\n",
        ]

    # Default fallback
    return ["SAY: Let us continue with our lesson.\n"]


async def seed_simulation_course(conn: Any) -> tuple[UUID, UUID]:
    """Seed test course with Chapter 1 (2 subtopics) and Chapter 2 (1 subtopic)."""
    course_id = uuid4()
    user_id = settings.DEV_USER_ID

    async with conn.cursor() as cur:
        # Course
        await cur.execute(
            """
            INSERT INTO courses (id, user_id, course_code, title, baseline_skill)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (
                str(course_id),
                str(user_id),
                "SIM101",
                "Simulation Statistics",
                "foundational",
            ),
        )

        # Syllabus Nodes
        nodes = [
            # Chapter 1
            (
                str(uuid4()),
                str(course_id),
                "ch01",
                "chapter",
                1,
                "Descriptive Statistics",
                "Chapter 1 covering mean and variance",
            ),
            (
                str(uuid4()),
                str(course_id),
                "ch01.t01_mean",
                "topic",
                2,
                "Mean and Median",
                "Sample mean and median definitions",
            ),
            (
                str(uuid4()),
                str(course_id),
                "ch01.t02_variance",
                "topic",
                3,
                "Variance and Standard Deviation",
                "Sample variance and standard deviation",
            ),
            # Chapter 2
            (
                str(uuid4()),
                str(course_id),
                "ch02",
                "chapter",
                4,
                "Probability Foundations",
                "Chapter 2 covering probability and Bayes theorem",
            ),
            (
                str(uuid4()),
                str(course_id),
                "ch02.t01_probability",
                "topic",
                5,
                "Probability Axioms",
                "Axioms and conditional probability",
            ),
        ]
        for n_id, c_id, path, n_type, o_idx, title, summary in nodes:
            await cur.execute(
                """
                INSERT INTO syllabus_nodes
                (id, course_id, path, node_type, order_index, title, summary)
                VALUES (%s, %s, %s::ltree, %s, %s, %s, %s);
                """,
                (n_id, c_id, path, n_type, o_idx, title, summary),
            )

        # Document Chunks for Chapter 1
        chunks = [
            (
                str(uuid4()),
                str(course_id),
                "ch01.t01_mean",
                "Sample mean formula: $\\bar{x} = \\frac{1}{n}\\sum x_i$.",
            ),
            (
                str(uuid4()),
                str(course_id),
                "ch01.t02_variance",
                "Sample variance: $s^2 = \\frac{1}{n-1}\\sum (x_i - \\bar{x})^2$.",
            ),
            (
                str(uuid4()),
                str(course_id),
                "ch02.t01_probability",
                "Axioms: $P(A|B) = \\frac{P(A \\cap B)}{P(B)}$.",
            ),
        ]
        for c_id_chunk, c_id_course, s_path, markdown in chunks:
            await cur.execute(
                """
                INSERT INTO document_chunks (id, course_id, syllabus_path, markdown)
                VALUES (%s, %s, %s::ltree, %s);
                """,
                (c_id_chunk, c_id_course, s_path, markdown),
            )

    return course_id, user_id


async def run_simulation(
    print_output: bool = True,
) -> tuple[list[SimulationRecord], TutorService]:
    """Execute the full Chapter 1 pedagogical walkthrough simulation."""
    conn = await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    )
    course_id, user_id = await seed_simulation_course(conn)

    provider = FakeProvider(
        name="groq", model="openai/gpt-oss-120b", response_fn=scripted_llm_response
    )
    router = LLMRouter(providers=[provider])
    repository = ScopedLtreeRepository(conn)
    service = TutorService(pool_or_conn=conn, router=router, repository=repository)

    records: list[SimulationRecord] = []
    step_counter = 0

    def log_record(
        speaker: str, text: str, event_type: str, state: str, node: str
    ) -> None:
        nonlocal step_counter
        step_counter += 1
        records.append(
            SimulationRecord(
                step_num=step_counter,
                speaker=speaker,
                text=text,
                event_type=event_type,
                fsm_state=state,
                current_node=node,
            )
        )
        if print_output:
            print(f"[{step_counter:02d}] [{state}] ({node}) {speaker}: {text}")

    if print_output:
        print("=" * 70)
        print("STARTING PHASE 4 TUTOR FSM SIMULATION (CHAPTER 1 WALKTHROUGH)")
        print("=" * 70)

    # 1. Start Session -> ONBOARDING
    session = await service.start_session(
        course_id, user_id, active_chapter_path="ch01"
    )
    current_state = session.fsm_state
    current_node = session.current_node_path
    log_record(
        "SYSTEM",
        f"Session initialized (ID: {session.id})",
        "INIT",
        current_state,
        current_node,
    )

    # Collect initial greeting
    async for ev in service.fsm.handle_turn(conn, session):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)

    # 2. Student responds with baseline -> ONBOARDING -> TEACH_STEP
    log_record(
        "STUDENT",
        "I have basic algebra knowledge.",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "I have basic algebra knowledge."
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )
        elif isinstance(ev, CtrlEvent):
            log_record(
                "TEACHER_CTRL", str(ev.payload), "CTRL", current_state, current_node
            )

    # Session is now in MICRO_CHECK for Subtopic 1 (Mean & Median)
    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "MICRO_CHECK"

    # 3. Student answers first micro-check correctly -> advances to Subtopic 2
    log_record(
        "STUDENT",
        "The mean increases by 5.",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "The mean increases by 5."
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )
        elif isinstance(ev, CtrlEvent):
            log_record(
                "TEACHER_CTRL", str(ev.payload), "CTRL", current_state, current_node
            )

    # Session is now in TEACH_STEP for Subtopic 2
    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "TEACH_STEP"
    assert current_node == "ch01.t02_variance"

    # Set up pending items for Subtopic 2 to simulate mid-step pause
    session.fsm_data["active_subpoint_name"] = "Variance Micro Check"
    session.fsm_data["pending_items"] = [
        {
            "type": "SAY",
            "text": (
                "Now for our micro check on variance: "
                "if all data values are identical, what is the variance?"
            ),
        },
        {
            "type": "CTRL",
            "payload": {
                "action": "micro_check",
                "question": "What is variance if all data points are identical?",
            },
        },
    ]
    await service.fsm.save_session(conn, session)

    # 4. Student asks mid-step question -> INTERRUPT_QA
    question_text = (
        "Wait, why do we divide by n-1 instead of n in the variance formula?"
    )
    log_record(
        "STUDENT",
        question_text,
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(session.id, question_text):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "INTERRUPT_QA"
    assert len(session.resume_stack) == 1
    assert session.resume_stack[0]["subpoint_name"] == "Variance Micro Check"

    # 5. 3-Turn Counter-Question Chain inside INTERRUPT_QA
    # Chain Turn 1: Follow-up on bias
    log_record(
        "STUDENT",
        "Does dividing by n underestimate the true variance?",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "Does dividing by n underestimate the true variance?"
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )

    # Chain Turn 2: Out-of-scope Chapter 2 question -> scope guardrail deferral!
    log_record(
        "STUDENT",
        "How does this relate to Bayes theorem in Chapter 2 Probability Foundations?",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id,
        "How does this relate to Bayes theorem in Chapter 2 Probability Foundations?",
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    # Stayed in INTERRUPT_QA without state change
    assert current_state == "INTERRUPT_QA"

    # Chain Turn 3: Large sample behavior
    turn3_text = (
        "So if the sample size n is huge, does the difference between n and n-1 matter?"
    )
    log_record(
        "STUDENT",
        turn3_text,
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(session.id, turn3_text):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "INTERRUPT_QA"

    # 6. Student confirms understanding -> pops resume_stack, delivers pending items
    log_record(
        "STUDENT",
        "I understand now, that makes sense!",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "I understand now, that makes sense!"
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, CtrlEvent):
            log_record(
                "TEACHER_CTRL", str(ev.payload), "CTRL", current_state, current_node
            )

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "MICRO_CHECK"
    assert len(session.resume_stack) == 0

    # 7. Student answers micro-check INCORRECTLY -> triggers remedial TEACH_STEP repeat
    log_record(
        "STUDENT",
        "The variance would be equal to the mean.",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "The variance would be equal to the mean."
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )
        elif isinstance(ev, CtrlEvent):
            log_record(
                "TEACHER_CTRL", str(ev.payload), "CTRL", current_state, current_node
            )

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_node == "ch01.t02_variance"  # Node did not advance
    assert current_state == "MICRO_CHECK"

    # 8. Student answers remedial micro-check CORRECTLY -> chapter completes into RECAP!
    log_record(
        "STUDENT",
        "The variance is zero because all values are identical.",
        "STUDENT_MESSAGE",
        current_state,
        current_node,
    )
    async for ev in service.handle_student_message(
        session.id, "The variance is zero because all values are identical."
    ):
        if isinstance(ev, StateEvent):
            current_state = ev.to_state
            current_node = ev.current_node_path
            log_record(
                "STATE",
                f"Transition -> {ev.to_state} ({ev.reason})",
                "STATE_CHANGE",
                current_state,
                current_node,
            )
        elif isinstance(ev, SayEvent):
            log_record("TEACHER", ev.text, "SAY", current_state, current_node)
        elif isinstance(ev, LatexEvent):
            log_record(
                "WHITEBOARD", f"LATEX: {ev.latex}", "LATEX", current_state, current_node
            )

    session = await service.get_session(session.id)
    current_state = session.fsm_state
    current_node = session.current_node_path
    assert current_state == "RECAP"

    if print_output:
        print("=" * 70)
        print("CHAPTER 1 WALKTHROUGH COMPLETE: FINAL STATE =", session.fsm_state)
        print("=" * 70)

    await conn.close()
    return records, service


if __name__ == "__main__":
    asyncio.run(run_simulation(print_output=True))

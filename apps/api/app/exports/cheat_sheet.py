"""Service for generating study cheat sheets from tutoring sessions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.schemas.session import (
    CheatSheetResponse,
    FormulaItem,
    MisconceptionItem,
)


def _clean_latex(raw: str) -> str:
    """Clean and strip redundant outer delimiters from LaTeX."""
    s = raw.strip()
    if s.startswith("$$") and s.endswith("$$") and len(s) >= 4 and "$$" not in s[2:-2]:
        s = s[2:-2].strip()
    elif s.startswith("$") and s.endswith("$") and len(s) >= 2 and "$" not in s[1:-1]:
        s = s[1:-1].strip()
    return s


async def generate_cheat_sheet(
    conn: Any,
    session_id: UUID,
) -> CheatSheetResponse:
    """Generate a clean study cheat sheet for a tutoring session.

    Collects all board formulas (raw LaTeX) and every misconception cleared
    during INTERRUPT_QA loops. Handles empty sessions gracefully.
    """
    # 1. Fetch session & course info
    session_query = """
        SELECT
            ts.id,
            ts.course_id,
            ts.active_chapter_path::text AS active_chapter_path,
            ts.current_node_path::text AS current_node_path,
            ts.fsm_state,
            ts.board_snapshot,
            ts.snapshot,
            ts.created_at,
            c.title AS course_title,
            c.course_code
        FROM tutor_sessions ts
        JOIN courses c ON ts.course_id = c.id
        WHERE ts.id = %s;
    """
    async with conn.cursor() as cur:
        await cur.execute(session_query, (str(session_id),))
        session_row = await cur.fetchone()

    if not session_row:
        raise ValueError(f"Session {session_id} not found")

    if isinstance(session_row, dict):
        course_id = UUID(str(session_row["course_id"]))
        active_chapter_path = str(session_row["active_chapter_path"])
        board_snapshot = session_row.get("board_snapshot") or {}
        snapshot = session_row.get("snapshot") or {}
        course_title = str(session_row.get("course_title", "Course"))
        course_code = str(session_row.get("course_code") or "")
        created_at = session_row.get("created_at") or datetime.now(timezone.utc)
    else:
        course_id = UUID(str(session_row[1]))
        active_chapter_path = str(session_row[2])
        board_snapshot = session_row[5] or {}
        snapshot = session_row[6] or {}
        course_title = str(session_row[8] if len(session_row) > 8 else "Course")
        course_code = str(
            session_row[9]
            if len(session_row) > 9 and session_row[9] is not None
            else ""
        )
        created_at = session_row[7] or datetime.now(timezone.utc)

    # 2. Fetch chapter title
    chapter_title = active_chapter_path
    chapter_query = """
        SELECT title, summary FROM syllabus_nodes
        WHERE course_id = %s AND path = %s::ltree
        LIMIT 1;
    """
    async with conn.cursor() as cur:
        await cur.execute(chapter_query, (str(course_id), active_chapter_path))
        ch_row = await cur.fetchone()
        if ch_row:
            if isinstance(ch_row, dict):
                chapter_title = ch_row.get("title") or active_chapter_path
            else:
                chapter_title = ch_row[0] or active_chapter_path

    # 3. Fetch all session events for formulas and misconceptions
    events_query = """
        SELECT turn_id, event_type, payload, created_at
        FROM session_events
        WHERE session_id = %s
        ORDER BY turn_id ASC, created_at ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(events_query, (str(session_id),))
        events = await cur.fetchall()

    formulas: list[FormulaItem] = []
    seen_formulas: set[str] = set()

    misconceptions: list[MisconceptionItem] = []
    seen_misconceptions: set[str] = set()

    for row in events:
        if isinstance(row, dict):
            turn_id = row["turn_id"]
            ev_type = row["event_type"]
            payload = row.get("payload") or {}
        else:
            turn_id = row[0]
            ev_type = row[1]
            payload = row[2] or {}

        # Formula detection
        raw_latex = ""
        label = ""
        op_id = ""

        if ev_type in ("LatexEvent", "latex"):
            raw_latex = payload.get("latex") or payload.get("raw") or ""
            label = payload.get("label") or f"Turn {turn_id} Formula"
            op_id = payload.get("op_id", "")
        elif ev_type == "BOARD_OP":
            if payload.get("op_type") == "latex":
                p_load = payload.get("payload", {})
                if isinstance(p_load, dict):
                    raw_latex = p_load.get("latex") or p_load.get("raw") or ""
                    label = p_load.get("label", "")
                else:
                    raw_latex = str(p_load)
                label = label or payload.get("label", f"Turn {turn_id} Formula")
                op_id = payload.get("op_id", "")

        if raw_latex:
            cleaned = _clean_latex(raw_latex)
            if cleaned and cleaned not in seen_formulas:
                seen_formulas.add(cleaned)
                formulas.append(
                    FormulaItem(
                        latex=cleaned,
                        label=label,
                        turn_id=turn_id,
                        op_id=op_id,
                    )
                )

        # Misconception / Interrupt resolution detection
        if ev_type == "MISCONCEPTION_CLEARED":
            q = payload.get("question", "").strip()
            ans = payload.get("clarification", "").strip()
            sub_path = payload.get("subtopic_path", "")
            sub_name = payload.get("subpoint_name", "")
            key = f"{q}:{ans}"
            if q and key not in seen_misconceptions:
                seen_misconceptions.add(key)
                misconceptions.append(
                    MisconceptionItem(
                        question=q,
                        clarification=ans,
                        subtopic_path=sub_path,
                        subtopic_title=sub_name or sub_path,
                        turn_id=turn_id,
                    )
                )

    # Also check board snapshots (active slide ops and archived slides) for formulas
    def _extract_from_ops(ops: list[Any]) -> None:
        for op in ops:
            if not isinstance(op, dict):
                continue
            op_type = (op.get("op_type") or "").lower()
            if op_type == "latex":
                p = op.get("payload", {})
                raw = ""
                lbl = op.get("label", "")
                if isinstance(p, dict):
                    raw = p.get("latex") or p.get("raw") or ""
                    lbl = lbl or p.get("label", "")
                elif isinstance(p, str):
                    raw = p
                cleaned = _clean_latex(raw)
                if cleaned and cleaned not in seen_formulas:
                    seen_formulas.add(cleaned)
                    formulas.append(
                        FormulaItem(
                            latex=cleaned,
                            label=lbl or f"Board Formula {len(formulas) + 1}",
                            turn_id=op.get("turn_id", 0),
                            op_id=op.get("op_id", ""),
                        )
                    )

    snap = snapshot or board_snapshot
    for slide in snap.get("slides", []):
        if isinstance(slide, dict):
            _extract_from_ops(slide.get("ops", []))
    _extract_from_ops(snap.get("active_slide_ops", []))

    # 4. Generate Markdown
    date_str = (
        created_at.strftime("%Y-%m-%d %H:%M UTC")
        if hasattr(created_at, "strftime")
        else str(created_at)
    )
    course_header = (
        f"{course_title} ({course_code})" if course_code else course_title
    )
    md_lines: list[str] = [
        f"# Study Cheat Sheet: {course_header}",
        f"## Chapter: {chapter_title} (`{active_chapter_path}`)",
        "",
        f"- **Session ID:** `{session_id}`",
        f"- **Date Generated:** {date_str}",
        f"- **Total Key Formulas:** {len(formulas)}",
        f"- **Misconceptions Cleared:** {len(misconceptions)}",
        "",
        "---",
        "",
        "### 📐 Key Mathematical Formulas",
        "",
    ]

    if formulas:
        for idx, f in enumerate(formulas, start=1):
            md_lines.append(f"#### {idx}. {f.label}")
            md_lines.append(f"$$\n{f.latex}\n$$")
            md_lines.append("")
    else:
        md_lines.append("*No formulas recorded during this tutoring session.*")
        md_lines.append("")

    md_lines.extend([
        "---",
        "",
        "### 💡 Cleared Misconceptions & Discussion",
        "",
    ])

    if misconceptions:
        for idx, m in enumerate(misconceptions, start=1):
            title = m.subtopic_title or m.subtopic_path or f"Discussion {idx}"
            md_lines.append(f"#### {idx}. {title}")
            md_lines.append(f"- **Student Question:** {m.question}")
            md_lines.append(f"- **Clarification:** {m.clarification}")
            md_lines.append("")
    else:
        md_lines.append(
            "*No misconceptions or interrupt questions were recorded for this session.*"
        )
        md_lines.append("")

    md_lines.extend([
        "---",
        "*Study guide generated by AI Video Tutor — $0 open academic architecture.*",
    ])

    markdown = "\n".join(md_lines)

    return CheatSheetResponse(
        session_id=session_id,
        course_id=course_id,
        chapter_path=active_chapter_path,
        chapter_title=chapter_title,
        markdown=markdown,
        formulas=formulas,
        misconceptions=misconceptions,
    )

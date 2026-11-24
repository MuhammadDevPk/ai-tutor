"""Read-only Course Mastery aggregation over session_events and syllabus."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.schemas.session import (
    ChapterMasteryItem,
    CourseMasteryResponse,
    WeakSubtopicItem,
)


async def get_course_mastery(
    conn: Any,
    course_id: UUID,
) -> CourseMasteryResponse:
    """Compute course mastery stats: chapter completion % and weak subtopics.

    Aggregates read-only over syllabus_nodes, tutor_sessions, and session_events.
    Weak subtopics are determined by the frequency of INTERRUPT_QA loops.
    """
    # 1. Fetch all chapter nodes for the course
    chapter_query = """
        SELECT path::text, title, order_index
        FROM syllabus_nodes
        WHERE course_id = %s AND (node_type = 'chapter' OR nlevel(path) = 1)
        ORDER BY order_index ASC;
    """
    async with conn.cursor() as cur:
        await cur.execute(chapter_query, (str(course_id),))
        chapter_rows = await cur.fetchall()

    chapters_map: dict[str, dict[str, Any]] = {}
    for r in chapter_rows:
        path = r["path"] if isinstance(r, dict) else r[0]
        title = r["title"] if isinstance(r, dict) else r[1]
        chapters_map[path] = {
            "path": path,
            "title": title,
            "completed": False,
            "sessions_count": 0,
            "interrupt_qa_count": 0,
        }

    # 2. Fetch all sessions for this course
    sessions_query = """
        SELECT id, active_chapter_path::text, fsm_state
        FROM tutor_sessions
        WHERE course_id = %s;
    """
    async with conn.cursor() as cur:
        await cur.execute(sessions_query, (str(course_id),))
        session_rows = await cur.fetchall()

    session_ids: list[str] = []
    session_to_chapter: dict[str, str] = {}
    for s in session_rows:
        sid = str(s["id"] if isinstance(s, dict) else s[0])
        ch_path = s["active_chapter_path"] if isinstance(s, dict) else s[1]
        state = s["fsm_state"] if isinstance(s, dict) else s[2]

        session_ids.append(sid)
        session_to_chapter[sid] = ch_path

        if ch_path in chapters_map:
            chapters_map[ch_path]["sessions_count"] += 1
            if state == "RECAP":
                chapters_map[ch_path]["completed"] = True

    # 3. Aggregate INTERRUPT_QA loops and misconceptions from session_events
    subtopic_interrupt_counts: dict[str, int] = {}
    subtopic_misconception_counts: dict[str, int] = {}

    if session_ids:
        # Check for RECAP transitions in session_events as well
        recap_query = """
            SELECT session_id, turn_id
            FROM session_events
            WHERE session_id = ANY(%s::uuid[])
              AND (event_type = 'STATE_CHANGE' AND payload->>'to_state' = 'RECAP');
        """
        async with conn.cursor() as cur:
            await cur.execute(recap_query, (session_ids,))
            recap_rows = await cur.fetchall()
            for r in recap_rows:
                sid = str(r["session_id"] if isinstance(r, dict) else r[0])
                ch = session_to_chapter.get(sid)
                if ch and ch in chapters_map:
                    chapters_map[ch]["completed"] = True

        # Count INTERRUPT_QA loops per chapter and per subtopic
        interrupt_query = """
            SELECT
                se.session_id,
                se.event_type,
                se.payload
            FROM session_events se
            WHERE se.session_id = ANY(%s::uuid[])
              AND (
                  (
                      se.event_type = 'STATE_CHANGE'
                      AND se.payload->>'to_state' = 'INTERRUPT_QA'
                  )
                  OR se.event_type = 'MISCONCEPTION_CLEARED'
              );
        """
        async with conn.cursor() as cur:
            await cur.execute(interrupt_query, (session_ids,))
            int_rows = await cur.fetchall()

        for r in int_rows:
            sid = str(r["session_id"] if isinstance(r, dict) else r[0])
            ev_type = r["event_type"] if isinstance(r, dict) else r[1]
            payload = r["payload"] if isinstance(r, dict) else r[2] or {}

            ch = session_to_chapter.get(sid)
            is_interrupt = (
                ev_type == "STATE_CHANGE"
                and payload.get("to_state") == "INTERRUPT_QA"
            )

            if is_interrupt and ch and ch in chapters_map:
                chapters_map[ch]["interrupt_qa_count"] += 1

            sub_path = (
                payload.get("current_node_path")
                or payload.get("subtopic_path")
                or payload.get("node_path")
                or ""
            )
            if sub_path:
                if ev_type == "MISCONCEPTION_CLEARED":
                    subtopic_misconception_counts[sub_path] = (
                        subtopic_misconception_counts.get(sub_path, 0) + 1
                    )
                elif is_interrupt:
                    subtopic_interrupt_counts[sub_path] = (
                        subtopic_interrupt_counts.get(sub_path, 0) + 1
                    )

    # 4. Resolve subtopic titles
    all_subtopic_paths = list(
        set(subtopic_interrupt_counts.keys())
        | set(subtopic_misconception_counts.keys())
    )
    subtopic_titles: dict[str, str] = {}
    if all_subtopic_paths:
        sub_query = """
            SELECT path::text, title
            FROM syllabus_nodes
            WHERE course_id = %s AND path::text = ANY(%s);
        """
        async with conn.cursor() as cur:
            await cur.execute(sub_query, (str(course_id), all_subtopic_paths))
            sub_rows = await cur.fetchall()
            for sr in sub_rows:
                p = sr["path"] if isinstance(sr, dict) else sr[0]
                t = sr["title"] if isinstance(sr, dict) else sr[1]
                subtopic_titles[p] = t

    # Build weak subtopics list sorted by interrupt count descending
    weak_subtopics: list[WeakSubtopicItem] = []
    for sp, count in sorted(
        subtopic_interrupt_counts.items(), key=lambda x: x[1], reverse=True
    ):
        weak_subtopics.append(
            WeakSubtopicItem(
                subtopic_path=sp,
                title=subtopic_titles.get(sp, sp),
                interrupt_count=count,
                misconception_count=subtopic_misconception_counts.get(sp, 0),
            )
        )

    # Build chapter items
    chapter_items: list[ChapterMasteryItem] = []
    completed_count = 0
    for ch_path, ch_info in chapters_map.items():
        if ch_info["completed"]:
            status = "completed"
            completed_count += 1
        elif ch_info["sessions_count"] > 0:
            status = "in_progress"
        else:
            status = "not_started"

        chapter_items.append(
            ChapterMasteryItem(
                chapter_path=ch_path,
                title=ch_info["title"],
                status=status,
                sessions_count=ch_info["sessions_count"],
                interrupt_qa_count=ch_info["interrupt_qa_count"],
            )
        )

    total_chapters = len(chapters_map)
    pct = (completed_count / total_chapters * 100.0) if total_chapters > 0 else 0.0

    return CourseMasteryResponse(
        course_id=course_id,
        total_chapters=total_chapters,
        completed_chapters=completed_count,
        completion_percentage=round(pct, 1),
        chapters=chapter_items,
        weak_subtopics=weak_subtopics,
    )

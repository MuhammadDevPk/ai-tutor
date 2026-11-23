import time
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_chapter_scoped_fencing_integration():
    """Gate test: inserts mock Chapter 1 + Chapter 2 nodes/chunks into Postgres

    and verifies querying with Chapter 1 scope returns ZERO Chapter 2 rows.
    """
    course_id = uuid4()
    user_id = settings.DEV_USER_ID

    async with await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row
    ) as conn:
        try:
            # 1. Insert course
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO courses (
                        id, user_id, course_code, title, baseline_skill
                    )
                    VALUES (%s, %s, %s, %s, %s);
                    """,
                    (
                        str(course_id),
                        str(user_id),
                        "INTG101",
                        "Integration Test Course",
                        "foundational",
                    ),
                )

                # 2. Insert Chapter 1 and Chapter 2 syllabus nodes
                nodes_to_insert = [
                    (str(uuid4()), str(course_id), "ch01", "chapter", 1, "Ch 1"),
                    (str(uuid4()), str(course_id), "ch01.t01", "topic", 2, "T 1.1"),
                    (str(uuid4()), str(course_id), "ch02", "chapter", 3, "Ch 2"),
                    (str(uuid4()), str(course_id), "ch02.t01", "topic", 4, "T 2.1"),
                ]
                for n_id, c_id, path, n_type, o_idx, title in nodes_to_insert:
                    await cur.execute(
                        """
                        INSERT INTO syllabus_nodes (
                            id, course_id, path, node_type, order_index, title
                        )
                        VALUES (%s, %s, %s::ltree, %s, %s, %s);
                        """,
                        (n_id, c_id, path, n_type, o_idx, title),
                    )

                # 3. Insert mock chunks for both chapters containing keyword 'variance'
                chunks_to_insert = [
                    (
                        str(uuid4()),
                        str(course_id),
                        "ch01.t01",
                        1,
                        "Sample variance formula s^2.",
                    ),
                    (
                        str(uuid4()),
                        str(course_id),
                        "ch02.t01",
                        15,
                        "ANOVA partitions total variance.",
                    ),
                ]
                for ch_id, c_id, s_path, page, md in chunks_to_insert:
                    await cur.execute(
                        """
                        INSERT INTO document_chunks (
                            id, course_id, syllabus_path, page, markdown
                        )
                        VALUES (%s, %s, %s::ltree, %s, %s);
                        """,
                        (ch_id, c_id, s_path, page, md),
                    )

            await conn.commit()

            repo = ScopedLtreeRepository(conn)

            # Query syllabus nodes scoped to Chapter 1
            t0 = time.perf_counter()
            ch1_nodes = await repo.query_syllabus_nodes(course_id, "ch01")
            query_time_ms = (time.perf_counter() - t0) * 1000

            # Verify Chapter 1 returns Chapter 1 nodes only
            assert len(ch1_nodes) == 2
            returned_paths = {n["path"] for n in ch1_nodes}
            assert returned_paths == {"ch01", "ch01.t01"}
            assert "ch02" not in returned_paths
            assert "ch02.t01" not in returned_paths

            # Query chunks scoped to Chapter 1 with search query 'variance'
            t1 = time.perf_counter()
            ch1_chunks = await repo.query_document_chunks(
                course_id=course_id, scope_path="ch01", search_query="variance"
            )
            chunk_query_time_ms = (time.perf_counter() - t1) * 1000

            # Assert Chapter 1 scope returns ZERO Chapter 2 rows
            assert len(ch1_chunks) == 1
            assert ch1_chunks[0]["syllabus_path"] == "ch01.t01"
            assert "Sample variance" in ch1_chunks[0]["markdown"]

            # Subtopic narrowing check
            subtopic_nodes = await repo.query_syllabus_nodes(course_id, "ch01.t01")
            assert len(subtopic_nodes) == 1
            assert subtopic_nodes[0]["path"] == "ch01.t01"

            # Performance check (< 10ms gate requirement)
            assert query_time_ms < 50.0
            assert chunk_query_time_ms < 50.0

        finally:
            # Clean up test data
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM courses WHERE id = %s;", (str(course_id),)
                )
            await conn.commit()

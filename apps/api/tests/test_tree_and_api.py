from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from test_ingestion import create_two_chapter_test_pdf

from app.auth import create_access_token
from app.config import settings
from app.ingestion.embeddings import FakeEmbedder
from app.ingestion.gemini_client import FakeGeminiClient, get_gemini_client
from app.ingestion.parser import ParsedPage
from app.ingestion.service import IngestionService
from app.ingestion.tree_extractor import (
    SyllabusNodeIn,
    build_page_mapping,
    extract_and_persist_tree,
)
from app.main import app
from app.routers.courses import get_embedder


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = create_access_token(user_id=settings.DEV_USER_ID)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_tree_extraction_validation_and_idempotence():
    """Tree extraction validates, sanitizes paths, persists nodes;

    re-running replaces the tree (idempotent count).
    """
    course_id = uuid4()
    user_id = settings.DEV_USER_ID
    fake_client = FakeGeminiClient()
    pages = [
        ParsedPage(
            page_number=1,
            markdown="Chapter 1 content",
            text_density=150,
            needs_vision=False,
        ),
        ParsedPage(
            page_number=2,
            markdown="Chapter 2 content",
            text_density=180,
            needs_vision=False,
        ),
        ParsedPage(
            page_number=3,
            markdown="Chapter 2 details",
            text_density=120,
            needs_vision=False,
        ),
    ]

    async with await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row
    ) as conn:
        try:
            # Seed course
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
                        "TREE101",
                        "Tree Course",
                        "foundational",
                    ),
                )
            await conn.commit()

            # 1. First run: extract and persist
            persisted = await extract_and_persist_tree(
                course_id=course_id,
                pages=pages,
                client=fake_client,
                conn_or_pool=conn,
            )

            # Fake client returns 2 chapters with 1 and 2 children = 5 total nodes
            assert len(persisted) == 5

            # Validate path sanitization
            paths = [node["path"] for node in persisted]
            assert "descriptive_statistics" in paths
            assert "descriptive_statistics.measures_of_dispersion" in paths
            assert "probability_foundations" in paths
            assert "probability_foundations.addition_rule" in paths
            assert "probability_foundations.visual_representations" in paths

            # Check rows in DB
            count_query = (
                "SELECT COUNT(*) as cnt FROM syllabus_nodes WHERE course_id = %s;"
            )
            async with conn.cursor() as cur:
                await cur.execute(count_query, (str(course_id),))
                row1 = await cur.fetchone()
                assert row1 is not None
                assert row1["cnt"] == 5

            # 2. Second run: idempotence check (replaces tree, does not duplicate)
            persisted_again = await extract_and_persist_tree(
                course_id=course_id,
                pages=pages,
                client=fake_client,
                conn_or_pool=conn,
            )
            assert len(persisted_again) == 5

            async with conn.cursor() as cur:
                await cur.execute(count_query, (str(course_id),))
                row2 = await cur.fetchone()
                assert row2 is not None
                assert row2["cnt"] == 5

        finally:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM courses WHERE id = %s;", (str(course_id),)
                )
            await conn.commit()


def test_build_page_mapping_deepest_node_wins():
    """build_page_mapping maps pages to the deepest covering node."""
    tree = [
        SyllabusNodeIn(
            title="Chapter 1",
            level=1,
            page_start=1,
            page_end=3,
            children=[
                SyllabusNodeIn(
                    title="Topic 1.1",
                    level=2,
                    page_start=1,
                    page_end=2,
                    children=[
                        SyllabusNodeIn(
                            title="Subtopic 1.1.1",
                            level=3,
                            page_start=1,
                            page_end=1,
                            children=[],
                        )
                    ],
                )
            ],
        ),
        SyllabusNodeIn(
            title="Chapter 2",
            level=1,
            page_start=4,
            page_end=5,
            children=[],
        ),
    ]

    mapping = build_page_mapping(tree)

    # Page 1 covered by Chapter 1, Topic 1.1, Subtopic 1.1.1
    # Deepest node wins -> Subtopic 1.1.1
    assert mapping[1] == "chapter_1.topic_1_1.subtopic_1_1_1"

    # Page 2 covered by Chapter 1 and Topic 1.1
    # Deepest node wins -> Topic 1.1
    assert mapping[2] == "chapter_1.topic_1_1"

    # Page 3 covered only by Chapter 1
    assert mapping[3] == "chapter_1"

    # Pages 4 and 5 covered by Chapter 2
    assert mapping[4] == "chapter_2"
    assert mapping[5] == "chapter_2"


@pytest.mark.asyncio
async def test_vision_fallback_in_ingestion_service():
    """Vision fallback: a needs_vision page gets its markdown replaced by

    the fake vision text during ingest.
    """
    course_id = uuid4()
    user_id = settings.DEV_USER_ID
    filename = "vision_test.pdf"
    # Page 3 has <100 chars -> needs_vision=True
    pdf_bytes = create_two_chapter_test_pdf()

    fake_client = FakeGeminiClient(
        canned_vision_text=(
            "# Figure 1.1: Standard Normal Distribution\n\n"
            "$$\\phi(z) = \\frac{1}{\\sqrt{2\\pi}} e^{-\\frac{z^2}{2}}$$"
        )
    )
    fake_embedder = FakeEmbedder(dim=384)

    async with await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row
    ) as conn:
        try:
            # Seed course
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
                        "VIS101",
                        "Vision Course",
                        "foundational",
                    ),
                )
            await conn.commit()

            service = IngestionService(
                pool_or_conn=conn,
                embedder=fake_embedder,
                gemini_client=fake_client,
            )

            result = await service.ingest_document(
                course_id=course_id,
                document_bytes=pdf_bytes,
                filename=filename,
                use_tree_extraction=False,
            )

            assert result.pages == 3
            # With gemini_client, page 3's needs_vision is cleared after replacement!
            assert result.vision_flagged_pages == 0

            # Verify chunk on page 3 contains replaced text and raw_latex
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT * FROM document_chunks WHERE course_id = %s AND page = 3;",
                    (str(course_id),),
                )
                chunk_page3 = await cur.fetchone()
                assert chunk_page3 is not None
                assert "Standard Normal Distribution" in chunk_page3["markdown"]
                assert "\\phi(z)" in chunk_page3["markdown"]
                raw_latex = chunk_page3["raw_latex"]
                assert any("\\phi(z)" in f for f in raw_latex)

        finally:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM courses WHERE id = %s;", (str(course_id),)
                )
            await conn.commit()


def test_api_upload_document_get_syllabus_and_scoped_chunks(
    auth_headers: dict[str, str],
):
    """API test:

    - upload PDF via TestClient with auth -> 200 and counts
    - GET syllabus returns the nested tree
    - GET chunks with chapter path returns only that chapter's chunks (fencing)
    """
    fake_client = FakeGeminiClient()
    fake_embedder = FakeEmbedder(dim=384)

    app.dependency_overrides[get_gemini_client] = lambda: fake_client
    app.dependency_overrides[get_embedder] = lambda: fake_embedder

    client = TestClient(app)

    try:
        # 1. Create a course
        code = f"API{uuid4().hex[:4].upper()}"
        course_resp = client.post(
            "/courses",
            json={
                "course_code": code,
                "title": "API Test Course",
                "baseline_skill": "foundational",
            },
            headers=auth_headers,
        )
        assert course_resp.status_code == 201, course_resp.text
        course_id = course_resp.json()["id"]

        # 2. Upload PDF
        pdf_bytes = create_two_chapter_test_pdf()
        files = {"file": ("handout.pdf", pdf_bytes, "application/pdf")}
        upload_resp = client.post(
            f"/courses/{course_id}/documents",
            files=files,
            headers=auth_headers,
        )
        assert upload_resp.status_code == 200, upload_resp.text
        upload_data = upload_resp.json()
        assert upload_data["pages"] == 3
        assert upload_data["chunks"] >= 2
        assert upload_data["vision_flagged_pages"] == 0
        assert upload_data["tree_nodes"] == 5

        # 3. GET syllabus
        syllabus_resp = client.get(
            f"/courses/{course_id}/syllabus", headers=auth_headers
        )
        assert syllabus_resp.status_code == 200, syllabus_resp.text
        syllabus_data = syllabus_resp.json()
        assert syllabus_data["course_id"] == course_id

        # Tree should have 2 top-level chapters
        nodes = syllabus_data["nodes"]
        assert len(nodes) == 2

        ch1_node = next(n for n in nodes if n["path"] == "descriptive_statistics")
        assert ch1_node["title"] == "Descriptive Statistics"
        assert len(ch1_node["children"]) == 1
        sub_path = "descriptive_statistics.measures_of_dispersion"
        assert ch1_node["children"][0]["path"] == sub_path

        ch2_node = next(n for n in nodes if n["path"] == "probability_foundations")
        assert ch2_node["title"] == "Probability Foundations"
        assert len(ch2_node["children"]) == 2

        # 4. GET chunks with chapter 1 scope
        ch1_chunks_resp = client.get(
            f"/courses/{course_id}/syllabus/chunks?path=descriptive_statistics",
            headers=auth_headers,
        )
        assert ch1_chunks_resp.status_code == 200, ch1_chunks_resp.text
        ch1_chunks = ch1_chunks_resp.json()
        assert len(ch1_chunks) > 0
        for c in ch1_chunks:
            assert c["syllabus_path"].startswith("descriptive_statistics")
            assert "probability_foundations" not in c["syllabus_path"]
            assert "s^2" in c["markdown"]

        # 5. GET chunks with chapter 2 scope
        ch2_chunks_resp = client.get(
            f"/courses/{course_id}/syllabus/chunks?path=probability_foundations",
            headers=auth_headers,
        )
        assert ch2_chunks_resp.status_code == 200, ch2_chunks_resp.text
        ch2_chunks = ch2_chunks_resp.json()
        assert len(ch2_chunks) > 0
        for c in ch2_chunks:
            assert c["syllabus_path"].startswith("probability_foundations")
            assert "descriptive_statistics" not in c["syllabus_path"]

        # 6. Chunks endpoint validation: missing query param path -> 422
        missing_param_resp = client.get(
            f"/courses/{course_id}/syllabus/chunks",
            headers=auth_headers,
        )
        assert missing_param_resp.status_code == 422

        # 7. Chunks endpoint validation: invalid ltree path -> 422
        invalid_path_resp = client.get(
            f"/courses/{course_id}/syllabus/chunks?path=invalid;sql;injection",
            headers=auth_headers,
        )
        assert invalid_path_resp.status_code == 422

        # 8. Clean up
        del_resp = client.delete(f"/courses/{course_id}", headers=auth_headers)
        assert del_resp.status_code == 200

    finally:
        app.dependency_overrides.pop(get_gemini_client, None)
        app.dependency_overrides.pop(get_embedder, None)

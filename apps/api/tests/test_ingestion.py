from typing import cast
from uuid import uuid4

import psycopg
import pymupdf
import pytest
from psycopg.rows import dict_row

from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository
from app.ingestion.chunker import (
    chunk_pages,
    extract_raw_latex,
    sanitize_heading_segment,
    sanitize_syllabus_path,
)
from app.ingestion.embeddings import FakeEmbedder, FastEmbedder
from app.ingestion.parser import detect_needs_vision, parse_pdf
from app.ingestion.service import IngestionService


def create_two_chapter_test_pdf() -> bytes:
    """Builds a real multi-page PDF using PyMuPDF (fitz) with two chapters

    containing display-math blocks and one low-text page.
    """
    doc = pymupdf.open()

    # Page 1: Chapter 1 with text and $$...$$ display math
    p1 = doc.new_page()
    ch1_text = (
        "# Chapter 1: Descriptive Statistics\n\n"
        "Descriptive statistics summarize and organize characteristics of data. "
        "A common measure of dispersion is sample variance, which quantifies "
        "the spread of observations around their arithmetic mean.\n\n"
        "$$s^2 = \\frac{1}{n-1}\\sum_{i=1}^n (x_i - \\bar{x})^2$$\n\n"
        "Dividing by n-1 applies Bessel correction to yield an unbiased estimator."
    )
    p1.insert_text((50, 72), ch1_text)

    # Page 2: Chapter 2 with text and \[...\] display math
    p2 = doc.new_page()
    ch2_text = (
        "# Chapter 2: Probability Foundations\n\n"
        "Probability theory models uncertainty in random experiments. For events "
        "A and B in sample space S, union probability uses the addition law.\n\n"
        "\\[P(A \\cup B) = P(A) + P(B) - P(A \\cap B)\\]\n\n"
        "When events are disjoint, the intersection probability is zero."
    )
    p2.insert_text((50, 72), ch2_text)

    # Page 3: Low-text page (< 100 characters) to trigger needs_vision flag
    p3 = doc.new_page()
    p3.insert_text((50, 72), "Figure 1.1")

    pdf_bytes = cast(bytes, doc.tobytes())
    doc.close()
    return pdf_bytes


def test_parser_per_page_and_vision_detector():
    """Requirement (a): Parser returns per-page markdown and low-text vision flag."""
    pdf_bytes = create_two_chapter_test_pdf()
    pages = parse_pdf(pdf_bytes)

    assert len(pages) == 3

    # Page 1: Contentful page with display math
    assert pages[0].page_number == 1
    assert pages[0].text_density > 100
    assert not pages[0].needs_vision
    assert "Descriptive Statistics" in pages[0].markdown
    assert "s^2" in pages[0].markdown

    # Page 2: Contentful page with probability formula
    assert pages[1].page_number == 2
    assert pages[1].text_density > 100
    assert not pages[1].needs_vision
    assert "Probability Foundations" in pages[1].markdown
    assert "P(A" in pages[1].markdown

    # Page 3: Low-text page (< 100 chars)
    assert pages[2].page_number == 3
    assert pages[2].text_density < 100
    assert pages[2].needs_vision is True

    # Unit check: broken glyph threshold (> 2% broken characters)
    broken_text = ("Sample text with replacement symbols " * 3) + ("\uFFFD" * 5)
    density, needs_vis_broken = detect_needs_vision(broken_text)
    assert density > 100
    assert needs_vis_broken is True

    # Clean text check
    clean_text = "Standard clean text without broken symbols " * 4
    _, needs_vis_clean = detect_needs_vision(clean_text)
    assert needs_vis_clean is False


def test_chunker_subtopic_fencing_and_math_preservation():
    """Requirement (b): Chunker never produces a chunk spanning two subtopics,

    never splits display-math blocks, and captures raw_latex.
    """
    pdf_bytes = create_two_chapter_test_pdf()
    pages = parse_pdf(pdf_bytes)
    course_id = uuid4()

    syllabus_mapping = [
        ((1, 1), "ch01.stats"),
        ((2, 2), "ch02.prob"),
    ]

    chunks = chunk_pages(
        course_id=course_id,
        pages=pages,
        syllabus_mapping=syllabus_mapping,
        source_filename="syllabus.pdf",
    )

    assert len(chunks) >= 2

    ch1_chunks = [c for c in chunks if c.syllabus_path == "ch01.stats"]
    ch2_chunks = [c for c in chunks if c.syllabus_path == "ch02.prob"]

    assert len(ch1_chunks) >= 1
    assert len(ch2_chunks) >= 1

    # 1. Chunker NEVER produces a chunk spanning two subtopics
    for chunk in ch1_chunks:
        assert chunk.course_id == course_id
        assert chunk.page == 1
        assert "Probability Foundations" not in chunk.markdown
        assert "P(A \\cup B)" not in chunk.markdown

    for chunk in ch2_chunks:
        assert chunk.course_id == course_id
        assert chunk.page == 2
        assert "Descriptive Statistics" not in chunk.markdown
        assert "s^2" not in chunk.markdown

    # 2. Display math blocks ($$...$$ and \[...\]) are never split
    ch1_math_chunk = next(c for c in ch1_chunks if "s^2" in c.markdown)
    expected_math_ch1 = "$$s^2 = \\frac{1}{n-1}\\sum_{i=1}^n (x_i - \\bar{x})^2$$"
    assert expected_math_ch1 in ch1_math_chunk.markdown

    ch2_math_chunk = next(c for c in ch2_chunks if "P(A" in c.markdown)
    expected_math_ch2 = "\\[P(A \\cup B) = P(A) + P(B) - P(A \\cap B)\\]"
    assert expected_math_ch2 in ch2_math_chunk.markdown

    # 3. Raw LaTeX blocks captured
    assert len(ch1_math_chunk.raw_latex) >= 1
    assert any("s^2" in formula for formula in ch1_math_chunk.raw_latex)

    assert len(ch2_math_chunk.raw_latex) >= 1
    assert any("P(A" in formula for formula in ch2_math_chunk.raw_latex)

    # 4. Heading-derived paths test
    heading_chunks = chunk_pages(
        course_id=course_id,
        pages=pages[:2],
        syllabus_mapping=None,
        source_filename="syllabus.pdf",
    )
    for c in heading_chunks:
        assert sanitize_syllabus_path(c.syllabus_path) == c.syllabus_path


def test_extract_raw_latex_and_sanitization():
    """Unit tests for math block extraction and ltree label sanitization."""
    md = (
        "Inline text with $$E = mc^2$$ and later \\[\\int_0^1 x dx\\] "
        "and \\begin{equation}y = mx + b\\end{equation}."
    )
    latex_blocks = extract_raw_latex(md)
    assert "E = mc^2" in latex_blocks
    assert "\\int_0^1 x dx" in latex_blocks
    assert "\\begin{equation}y = mx + b\\end{equation}" in latex_blocks

    # Sanitization checks
    assert sanitize_heading_segment("1.1 Mean & Variance!") == "1_1_mean_variance"
    assert sanitize_heading_segment("   ") == "sec"
    assert sanitize_syllabus_path("ch01..1_1_mean") == "ch01.1_1_mean"


@pytest.mark.asyncio
async def test_ingestion_idempotence_and_ltree_scoping():
    """Requirements (c) and (d):

    (c) Ingestion is idempotent: ingesting twice leaves chunk count unchanged.
    (d) Chunks are retrievable under chapter scope and NOT other chapter scope.
    """
    course_id = uuid4()
    user_id = settings.DEV_USER_ID
    filename = "handout_sta101.pdf"
    pdf_bytes = create_two_chapter_test_pdf()

    syllabus_mapping = [
        ((1, 1), "ch01.stats"),
        ((2, 2), "ch02.prob"),
    ]
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
                        "INGEST101",
                        "Ingestion Course",
                        "foundational",
                    ),
                )
            await conn.commit()

            # First ingestion run
            service = IngestionService(pool_or_conn=conn, embedder=fake_embedder)
            res1 = await service.ingest_document(
                course_id=course_id,
                document_bytes=pdf_bytes,
                filename=filename,
                syllabus_assignment=syllabus_mapping,
            )

            assert res1.pages == 3
            assert res1.chunks >= 2
            assert res1.vision_flagged_pages == 1

            # Count chunks in DB after first run
            count_query = (
                "SELECT COUNT(*) as cnt FROM document_chunks "
                "WHERE course_id = %s AND source_filename = %s;"
            )
            async with conn.cursor() as cur:
                await cur.execute(count_query, (str(course_id), filename))
                row1 = await cur.fetchone()
                assert row1 is not None
                initial_count = row1["cnt"]
                assert initial_count == res1.chunks

            # Second ingestion run (idempotence verification)
            res2 = await service.ingest_document(
                course_id=course_id,
                document_bytes=pdf_bytes,
                filename=filename,
                syllabus_assignment=syllabus_mapping,
            )

            assert res2.chunks == res1.chunks

            # Count chunks in DB after second run — must be IDENTICAL (not doubled)
            async with conn.cursor() as cur:
                await cur.execute(count_query, (str(course_id), filename))
                row2 = await cur.fetchone()
                assert row2 is not None
                assert row2["cnt"] == initial_count

            # (d) Verify scoped retrieval via ScopedLtreeRepository
            repo = ScopedLtreeRepository(conn)

            # Query Chapter 1 scope
            ch1_chunks = await repo.query_document_chunks(
                course_id=course_id, scope_path="ch01"
            )
            assert len(ch1_chunks) > 0
            for chunk in ch1_chunks:
                assert str(chunk["course_id"]) == str(course_id)
                assert chunk["syllabus_path"].startswith("ch01")
                assert "ch02" not in chunk["syllabus_path"]
                assert chunk["source_filename"] == filename

            # Query Chapter 2 scope
            ch2_chunks = await repo.query_document_chunks(
                course_id=course_id, scope_path="ch02"
            )
            assert len(ch2_chunks) > 0
            for chunk in ch2_chunks:
                assert str(chunk["course_id"]) == str(course_id)
                assert chunk["syllabus_path"].startswith("ch02")
                assert "ch01" not in chunk["syllabus_path"]
                assert chunk["source_filename"] == filename

        finally:
            # Clean up test course and cascading chunks
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM courses WHERE id = %s;", (str(course_id),)
                )
            await conn.commit()


@pytest.mark.slow
def test_real_fastembed_embedder_dimension():
    """Verifies real FastEmbedder with BAAI/bge-small-en-v1.5 gives 384-dim vectors."""
    embedder = FastEmbedder()
    results = embedder.embed_texts(["Mathematical physics and statistics sample."])
    assert len(results) == 1
    assert len(results[0]) == 384

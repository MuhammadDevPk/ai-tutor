import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.ltree_repository import sanitize_ltree_path
from app.ingestion.parser import ParsedPage

# Matches display math blocks ($$...$$, \[...\], \begin{...}...\end{...})
DISPLAY_MATH_REGEX = re.compile(
    r"(\$\$.*?\$\$|\\\[.*?\\\]|\\begin\{[a-zA-Z*]+\}.*?\\end\{[a-zA-Z*]+\})",
    re.DOTALL,
)

HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.*)$")


class DocumentChunk(BaseModel):
    course_id: UUID
    syllabus_path: str
    page: int
    markdown: str
    raw_latex: list[str] = Field(default_factory=list)
    source_filename: str | None = None


def sanitize_heading_segment(segment: str) -> str:
    """Sanitizes a string into a valid ltree label matching [A-Za-z0-9_]+."""
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", segment.strip().lower()).strip("_")
    return cleaned if cleaned else "sec"


def sanitize_syllabus_path(path: str) -> str:
    """Sanitizes a dot-separated syllabus path where each segment is valid ltree."""
    segments = [sanitize_heading_segment(s) for s in path.split(".") if s.strip()]
    cleaned_path = ".".join(segments) if segments else "root"
    return sanitize_ltree_path(cleaned_path)


def extract_raw_latex(markdown: str) -> list[str]:
    """Extracts raw LaTeX expressions from display math blocks and environments."""
    matches = DISPLAY_MATH_REGEX.findall(markdown)
    results: list[str] = []
    for match in matches:
        text = match.strip()
        if text.startswith("$$") and text.endswith("$$"):
            expr = text[2:-2].strip()
        elif text.startswith(r"\[") and text.endswith(r"\]"):
            expr = text[2:-2].strip()
        else:
            expr = text
        if expr and expr not in results:
            results.append(expr)
    return results


def resolve_syllabus_path_for_page(
    page_number: int,
    syllabus_mapping: Any,
) -> str | None:
    """Finds assigned syllabus path for a page from page ranges or dictionary."""
    if not syllabus_mapping:
        return None

    if isinstance(syllabus_mapping, dict):
        path = syllabus_mapping.get(page_number)
        return sanitize_syllabus_path(path) if path else None

    if isinstance(syllabus_mapping, list):
        for item in syllabus_mapping:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            key, path = item
            if isinstance(key, (tuple, list)) and len(key) == 2:
                start_p, end_p = key
                if start_p <= page_number <= end_p:
                    return sanitize_syllabus_path(path)
            elif isinstance(key, int):
                if key == page_number:
                    return sanitize_syllabus_path(path)

    return None


def _split_into_atomic_blocks(text: str) -> list[str]:
    """Splits markdown into atomic blocks without splitting math blocks."""
    if not text.strip():
        return []

    # 1. Protect display math blocks using placeholders
    math_map: dict[str, str] = {}

    def _replace_math(match: re.Match[str]) -> str:
        idx = len(math_map)
        token = f"__MATH_BLOCK_TOKEN_{idx}__"
        math_map[token] = match.group(0)
        return token

    protected_text = DISPLAY_MATH_REGEX.sub(_replace_math, text)

    # 2. Split text by paragraphs (2 or more newlines)
    raw_blocks = re.split(r"\n\s*\n", protected_text)
    atomic_blocks: list[str] = []

    for raw in raw_blocks:
        stripped = raw.strip()
        if not stripped:
            continue

        # Check if this block contains multiple lines with a heading
        lines = stripped.split("\n")
        current_sub_lines: list[str] = []
        for line in lines:
            if HEADING_REGEX.match(line.strip()):
                if current_sub_lines:
                    atomic_blocks.append("\n".join(current_sub_lines).strip())
                    current_sub_lines = []
                atomic_blocks.append(line.strip())
            else:
                current_sub_lines.append(line)
        if current_sub_lines:
            atomic_blocks.append("\n".join(current_sub_lines).strip())

    # 3. Restore protected display math blocks
    restored_blocks: list[str] = []
    for block in atomic_blocks:
        restored = block
        for token, original_math in math_map.items():
            if token in restored:
                restored = restored.replace(token, original_math)
        if restored.strip():
            restored_blocks.append(restored.strip())

    return restored_blocks


def chunk_pages(
    course_id: UUID,
    pages: list[ParsedPage],
    syllabus_mapping: Any = None,
    source_filename: str | None = None,
    target_chunk_size: int = 1200,
) -> list[DocumentChunk]:
    r"""Chunks structured pages into subtopic-scoped, formula-preserving chunks.

    Hard Invariants:
    1. A chunk NEVER spans two subtopics.
    2. Display math blocks ($$...$$ and \[...\]) are never split.
    3. Raw LaTeX blocks are extracted into raw_latex list per chunk.
    4. Target chunk size ~1200 chars with splits only at paragraph/heading boundaries.
    5. Every chunk carries course_id, syllabus_path, page number.
    """
    chunks: list[DocumentChunk] = []

    # Maintain state across pages for heading-derived paths
    active_chapter_path = "ch01"
    active_subtopic_path = "ch01.intro"

    for page in pages:
        mapped_path = resolve_syllabus_path_for_page(page.page_number, syllabus_mapping)
        atomic_blocks = _split_into_atomic_blocks(page.markdown)
        if not atomic_blocks:
            continue

        # If a page mapping exists, the entire page belongs to mapped_path
        if mapped_path is not None:
            current_subtopic = mapped_path
            current_chunk_blocks: list[str] = []
            current_chunk_len = 0

            for block in atomic_blocks:
                block_len = len(block)
                if current_chunk_blocks and (
                    current_chunk_len + block_len + 2 > target_chunk_size
                ):
                    chunk_text = "\n\n".join(current_chunk_blocks).strip()
                    chunks.append(
                        DocumentChunk(
                            course_id=course_id,
                            syllabus_path=current_subtopic,
                            page=page.page_number,
                            markdown=chunk_text,
                            raw_latex=extract_raw_latex(chunk_text),
                            source_filename=source_filename,
                        )
                    )
                    current_chunk_blocks = [block]
                    current_chunk_len = block_len
                else:
                    current_chunk_blocks.append(block)
                    current_chunk_len += block_len + (
                        2 if current_chunk_len > 0 else 0
                    )

            if current_chunk_blocks:
                chunk_text = "\n\n".join(current_chunk_blocks).strip()
                chunks.append(
                    DocumentChunk(
                        course_id=course_id,
                        syllabus_path=current_subtopic,
                        page=page.page_number,
                        markdown=chunk_text,
                        raw_latex=extract_raw_latex(chunk_text),
                        source_filename=source_filename,
                    )
                )

        else:
            # Heading-derived paths mode: headings define subtopics
            current_chunk_blocks = []
            current_chunk_len = 0

            for block in atomic_blocks:
                heading_match = HEADING_REGEX.match(block.strip())
                if heading_match:
                    # Flush current chunk before switching subtopic
                    if current_chunk_blocks:
                        chunk_text = "\n\n".join(current_chunk_blocks).strip()
                        chunks.append(
                            DocumentChunk(
                                course_id=course_id,
                                syllabus_path=active_subtopic_path,
                                page=page.page_number,
                                markdown=chunk_text,
                                raw_latex=extract_raw_latex(chunk_text),
                                source_filename=source_filename,
                            )
                        )
                        current_chunk_blocks = []
                        current_chunk_len = 0

                    hashes = heading_match.group(1)
                    title = heading_match.group(2).strip()
                    slug = sanitize_heading_segment(title)

                    if len(hashes) == 1:
                        # Top-level chapter heading
                        active_chapter_path = slug
                        active_subtopic_path = slug
                    else:
                        # Subtopic heading
                        active_subtopic_path = sanitize_syllabus_path(
                            f"{active_chapter_path}.{slug}"
                        )

                    # Include heading in the new chunk
                    current_chunk_blocks.append(block)
                    current_chunk_len = len(block)
                    continue

                # Normal content block
                block_len = len(block)
                if current_chunk_blocks and (
                    current_chunk_len + block_len + 2 > target_chunk_size
                ):
                    chunk_text = "\n\n".join(current_chunk_blocks).strip()
                    chunks.append(
                        DocumentChunk(
                            course_id=course_id,
                            syllabus_path=active_subtopic_path,
                            page=page.page_number,
                            markdown=chunk_text,
                            raw_latex=extract_raw_latex(chunk_text),
                            source_filename=source_filename,
                        )
                    )
                    current_chunk_blocks = [block]
                    current_chunk_len = block_len
                else:
                    current_chunk_blocks.append(block)
                    current_chunk_len += block_len + (
                        2 if current_chunk_len > 0 else 0
                    )

            if current_chunk_blocks:
                chunk_text = "\n\n".join(current_chunk_blocks).strip()
                chunks.append(
                    DocumentChunk(
                        course_id=course_id,
                        syllabus_path=active_subtopic_path,
                        page=page.page_number,
                        markdown=chunk_text,
                        raw_latex=extract_raw_latex(chunk_text),
                        source_filename=source_filename,
                    )
                )

    return chunks

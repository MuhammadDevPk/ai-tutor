from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm
from pydantic import BaseModel


class ParsedPage(BaseModel):
    page_number: int  # 1-indexed
    markdown: str
    text_density: int
    needs_vision: bool


def is_broken_or_replacement_char(char: str) -> bool:
    """Checks if character is a replacement char or in Unicode Private Use Areas."""
    cp = ord(char)
    # Unicode replacement character
    if cp == 0xFFFD:
        return True
    # BMP Private Use Area: U+E000 - U+F8FF
    if 0xE000 <= cp <= 0xF8FF:
        return True
    # Supplementary Private Use Area-A: U+F0000 - U+FFFFD
    if 0xF0000 <= cp <= 0xFFFFD:
        return True
    # Supplementary Private Use Area-B: U+100000 - U+10FFFD
    if 0x100000 <= cp <= 0x10FFFD:
        return True
    return False


def detect_needs_vision(text: str) -> tuple[int, bool]:
    """Computes text_density and determines if page needs vision fallback.

    Flags a page when:
    1. Extractable text is very low (< 100 characters).
    2. Fraction of replacement / broken glyph characters is high (> 2% of chars).
    """
    cleaned = text.strip()
    text_density = len(cleaned)

    # 1. Very low extractable text (< 100 characters)
    if text_density < 100:
        return text_density, True

    # 2. Fraction of broken glyphs > 2% of characters
    total_len = len(text)
    if total_len > 0:
        broken_count = sum(1 for c in text if is_broken_or_replacement_char(c))
        if (broken_count / total_len) > 0.02:
            return text_density, True

    return text_density, False


def parse_pdf(pdf_source: bytes | str | Path) -> list[ParsedPage]:
    """Converts a PDF into structured per-page Markdown.

    Preserves mathematical notation via PyMuPDF4LLM and calculates text density
    and a needs_vision flag.
    """
    doc: Any = None
    if isinstance(pdf_source, (str, Path)):
        doc = pymupdf.open(str(pdf_source))
    elif isinstance(pdf_source, (bytes, bytearray)):
        doc = pymupdf.open(stream=bytes(pdf_source), filetype="pdf")
    else:
        raise TypeError(f"Unsupported pdf_source type: {type(pdf_source)}")

    try:
        page_chunks = pymupdf4llm.to_markdown(doc, page_chunks=True)
        pages: list[ParsedPage] = []

        if not page_chunks and len(doc) > 0:
            for page_idx in range(len(doc)):
                pages.append(
                    ParsedPage(
                        page_number=page_idx + 1,
                        markdown="",
                        text_density=0,
                        needs_vision=True,
                    )
                )
            return pages

        for idx, chunk in enumerate(page_chunks):
            metadata = chunk.get("metadata", {})
            page_num = metadata.get("page_number") or metadata.get("page") or (idx + 1)
            raw_text = chunk.get("text", "")

            density, needs_vision = detect_needs_vision(raw_text)
            pages.append(
                ParsedPage(
                    page_number=int(page_num),
                    markdown=raw_text,
                    text_density=density,
                    needs_vision=needs_vision,
                )
            )

        return pages
    finally:
        if doc is not None:
            doc.close()

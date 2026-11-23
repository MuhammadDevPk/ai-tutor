import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pymupdf
from pydantic import BaseModel

from app.db.connection import get_db_pool
from app.ingestion.chunker import DocumentChunk, chunk_pages
from app.ingestion.embeddings import BaseEmbedder, FastEmbedder
from app.ingestion.gemini_client import GeminiClient
from app.ingestion.parser import ParsedPage, parse_pdf
from app.ingestion.tree_extractor import build_page_mapping, extract_and_persist_tree


class IngestionResult(BaseModel):
    pages: int
    chunks: int
    vision_flagged_pages: int
    tree_nodes: int = 0


class IngestionService:
    """Service orchestrating PDF parsing, optional Gemini Vision fallback,

    curriculum tree extraction, math-aware chunking, embedding,
    and idempotent bulk insertion into document_chunks.
    """

    def __init__(
        self,
        pool_or_conn: Any = None,
        embedder: BaseEmbedder | None = None,
        gemini_client: GeminiClient | None = None,
    ):
        self._pool_or_conn = pool_or_conn
        self._embedder = embedder or FastEmbedder()
        self._gemini_client = gemini_client

    @asynccontextmanager
    async def _get_conn(self) -> AsyncGenerator[Any, None]:
        target = self._pool_or_conn or get_db_pool()
        if callable(getattr(target, "connection", None)):
            async with target.connection() as conn:
                yield conn
        else:
            yield target

    async def ingest_document(
        self,
        course_id: UUID,
        document_bytes: bytes,
        filename: str,
        syllabus_assignment: Any = None,
        use_tree_extraction: bool = False,
    ) -> IngestionResult:
        # 1. Parse PDF into per-page Markdown with needs_vision detection
        parsed_pages: list[ParsedPage] = parse_pdf(document_bytes)
        page_count = len(parsed_pages)

        # 2. Vision fallback: render pages with needs_vision to PNG
        # and transcribe with Gemini
        if self._gemini_client is not None:
            doc: Any = None
            try:
                for page in parsed_pages:
                    if page.needs_vision:
                        if doc is None:
                            doc = pymupdf.open(
                                stream=bytes(document_bytes), filetype="pdf"
                            )
                        p_idx = page.page_number - 1
                        if 0 <= p_idx < len(doc):
                            pdf_page = doc[p_idx]
                            pix = pdf_page.get_pixmap()
                            png_bytes = pix.tobytes("png")
                            vision_text = self._gemini_client.vision_extract_text(
                                page_image_png=png_bytes,
                                page_number=page.page_number,
                            )
                            if vision_text and vision_text.strip():
                                page.markdown = vision_text.strip()
                                page.needs_vision = False
            finally:
                if doc is not None:
                    doc.close()

        vision_flagged = sum(1 for p in parsed_pages if p.needs_vision)

        # 3. Optional Gemini tree extraction & curriculum page mapping
        tree_node_count = 0
        if use_tree_extraction and self._gemini_client is not None:
            persisted_nodes = await extract_and_persist_tree(
                course_id=course_id,
                pages=parsed_pages,
                client=self._gemini_client,
                conn_or_pool=self._pool_or_conn,
            )
            tree_node_count = len(persisted_nodes)
            syllabus_assignment = build_page_mapping(persisted_nodes)

        # 4. Chunk pages according to subtopics and display math boundaries
        chunks: list[DocumentChunk] = chunk_pages(
            course_id=course_id,
            pages=parsed_pages,
            syllabus_mapping=syllabus_assignment,
            source_filename=filename,
        )
        chunk_count = len(chunks)

        # 5. Embed chunks (batched)
        if chunks:
            texts = [c.markdown for c in chunks]
            embeddings = self._embedder.embed_texts(texts)
        else:
            embeddings = []

        # 6. Idempotent bulk insertion (delete-then-insert per course_id + filename)
        async with self._get_conn() as conn:
            async with conn.transaction():
                async with conn.cursor() as cur:
                    delete_query = (
                        "DELETE FROM document_chunks "
                        "WHERE course_id = %s AND source_filename = %s;"
                    )
                    await cur.execute(delete_query, (str(course_id), filename))

                    if chunks:
                        insert_query = """
                        INSERT INTO document_chunks (
                            id, course_id, syllabus_path, page,
                            markdown, raw_latex, embedding, source_filename
                        )
                        VALUES (%s, %s, %s::ltree, %s, %s, %s::jsonb, %s::vector, %s);
                        """
                        params_list = []
                        for chunk, emb in zip(chunks, embeddings, strict=True):
                            chunk_id = str(uuid4())
                            emb_str = (
                                f"[{','.join(str(x) for x in emb)}]"
                                if emb
                                else None
                            )
                            raw_latex_json = json.dumps(chunk.raw_latex)
                            params_list.append(
                                (
                                    chunk_id,
                                    str(chunk.course_id),
                                    chunk.syllabus_path,
                                    chunk.page,
                                    chunk.markdown,
                                    raw_latex_json,
                                    emb_str,
                                    chunk.source_filename,
                                )
                            )
                        await cur.executemany(insert_query, params_list)

        return IngestionResult(
            pages=page_count,
            chunks=chunk_count,
            vision_flagged_pages=vision_flagged,
            tree_nodes=tree_node_count,
        )


async def ingest_document(
    course_id: UUID,
    document_bytes: bytes,
    filename: str,
    syllabus_assignment: Any = None,
    pool_or_conn: Any = None,
    embedder: BaseEmbedder | None = None,
    gemini_client: GeminiClient | None = None,
    use_tree_extraction: bool = False,
) -> IngestionResult:
    service = IngestionService(
        pool_or_conn=pool_or_conn,
        embedder=embedder,
        gemini_client=gemini_client,
    )
    return await service.ingest_document(
        course_id=course_id,
        document_bytes=document_bytes,
        filename=filename,
        syllabus_assignment=syllabus_assignment,
        use_tree_extraction=use_tree_extraction,
    )

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.db.connection import get_db_pool
from app.ingestion.chunker import sanitize_heading_segment, sanitize_syllabus_path
from app.ingestion.gemini_client import GeminiClient
from app.ingestion.parser import ParsedPage
from app.schemas.syllabus import SyllabusNodeResponse


class SyllabusNodeIn(BaseModel):
    title: str
    level: int = 1
    page_start: int
    page_end: int
    children: list["SyllabusNodeIn"] = Field(default_factory=list)
    path: str | None = None


def _parse_raw_tree(raw_tree: Any) -> list[SyllabusNodeIn]:
    """Defensively parses raw JSON tree into a list of SyllabusNodeIn models."""
    if isinstance(raw_tree, dict):
        if "chapters" in raw_tree and isinstance(raw_tree["chapters"], list):
            items = raw_tree["chapters"]
        elif "nodes" in raw_tree and isinstance(raw_tree["nodes"], list):
            items = raw_tree["nodes"]
        elif "title" in raw_tree:
            items = [raw_tree]
        else:
            items = []
    elif isinstance(raw_tree, list):
        items = raw_tree
    else:
        items = []

    return [SyllabusNodeIn.model_validate(item) for item in items]


def _assign_paths_and_flatten(
    nodes: list[SyllabusNodeIn],
    parent_path: str | None = None,
) -> list[SyllabusNodeIn]:
    """Recursively assigns sanitized dot-separated ltree paths and flattens nodes."""
    flattened: list[SyllabusNodeIn] = []
    for node in nodes:
        segment = sanitize_heading_segment(node.title)
        if parent_path:
            full_path = sanitize_syllabus_path(f"{parent_path}.{segment}")
        else:
            full_path = sanitize_syllabus_path(segment)

        node.path = full_path
        flattened.append(node)

        if node.children:
            child_nodes = _assign_paths_and_flatten(
                node.children, parent_path=full_path
            )
            flattened.extend(child_nodes)

    return flattened


def build_page_mapping(tree: Any) -> dict[int, str]:
    """Builds a mapping: page_number -> leaf syllabus_path covering that page.

    The deepest covering node wins.
    """
    if isinstance(tree, list) and all(
        isinstance(x, dict) and "path" in x for x in tree
    ):
        # Already flattened dicts with paths
        node_dicts = tree
    else:
        # Pydantic or raw tree structure
        if isinstance(tree, list) and all(isinstance(x, SyllabusNodeIn) for x in tree):
            nodes = tree
        else:
            nodes = _parse_raw_tree(tree)
        flattened_nodes = _assign_paths_and_flatten(nodes)
        node_dicts = [
            {
                "path": n.path or "root",
                "level": n.level,
                "page_start": n.page_start,
                "page_end": n.page_end,
                "has_children": bool(n.children),
            }
            for n in flattened_nodes
        ]

    # Map page -> (depth, is_leaf, path)
    page_records: dict[int, tuple[int, bool, str]] = {}

    for n in node_dicts:
        path = str(n.get("path") or "root")
        depth = len(path.split("."))
        # If explicitly passed or has_children
        is_leaf = not n.get("has_children", False)
        page_start = int(n.get("page_start", 1))
        page_end = int(n.get("page_end", page_start))

        for p in range(page_start, page_end + 1):
            if p not in page_records:
                page_records[p] = (depth, is_leaf, path)
            else:
                curr_depth, curr_leaf, _ = page_records[p]
                # Deepest node wins; if equal depth, leaf wins
                if depth > curr_depth:
                    page_records[p] = (depth, is_leaf, path)
                elif depth == curr_depth and is_leaf and not curr_leaf:
                    page_records[p] = (depth, is_leaf, path)

    return {p: rec[2] for p, rec in page_records.items()}


@asynccontextmanager
async def _get_conn(pool_or_conn: Any) -> AsyncGenerator[Any, None]:
    target = pool_or_conn or get_db_pool()
    if callable(getattr(target, "connection", None)):
        async with target.connection() as conn:
            yield conn
    else:
        yield target


async def extract_and_persist_tree(
    course_id: UUID,
    pages: list[ParsedPage],
    client: GeminiClient,
    conn_or_pool: Any = None,
) -> list[dict[str, Any]]:
    """Extracts curriculum tree via GeminiClient, validates with Pydantic,

    sanitizes ltree paths, and persists rows into syllabus_nodes idempotently.
    """
    # 1. Call Gemini client
    raw_tree = client.extract_tree(pages)

    # 2. Validate with Pydantic
    root_nodes = _parse_raw_tree(raw_tree)

    # 3. Sanitize path segments and build full ltree paths
    flattened = _assign_paths_and_flatten(root_nodes)

    # 4. Persist idempotently inside transaction (delete existing tree for course first)
    persisted_rows: list[dict[str, Any]] = []

    async with _get_conn(conn_or_pool) as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                # Delete existing tree for this course
                await cur.execute(
                    "DELETE FROM syllabus_nodes WHERE course_id = %s;",
                    (str(course_id),),
                )

                insert_sql = """
                INSERT INTO syllabus_nodes (
                    id, course_id, path, node_type, order_index,
                    title, level, page_start, page_end
                )
                VALUES (%s, %s, %s::ltree, %s, %s, %s, %s, %s, %s)
                RETURNING id, course_id, path;
                """
                for idx, node in enumerate(flattened):
                    node_id = str(uuid4())
                    node_type = (
                        "chapter"
                        if node.level == 1
                        else ("topic" if node.level == 2 else "subtopic")
                    )
                    path_str = node.path or "root"
                    await cur.execute(
                        insert_sql,
                        (
                            node_id,
                            str(course_id),
                            path_str,
                            node_type,
                            idx,
                            node.title,
                            node.level,
                            node.page_start,
                            node.page_end,
                        ),
                    )
                    persisted_rows.append(
                        {
                            "id": node_id,
                            "course_id": str(course_id),
                            "path": path_str,
                            "node_type": node_type,
                            "order_index": idx,
                            "title": node.title,
                            "level": node.level,
                            "page_start": node.page_start,
                            "page_end": node.page_end,
                            "has_children": bool(node.children),
                        }
                    )

    return persisted_rows


def assemble_tree(rows: list[dict[str, Any]]) -> list[SyllabusNodeResponse]:
    """Assembles flat syllabus_nodes database rows into a nested recursive tree."""
    node_map: dict[str, SyllabusNodeResponse] = {}
    roots: list[SyllabusNodeResponse] = []

    for row in rows:
        node = SyllabusNodeResponse(
            id=row["id"],
            course_id=row["course_id"],
            path=str(row["path"]),
            node_type=row.get("node_type", "chapter"),
            order_index=row.get("order_index", 0),
            title=row["title"],
            level=row.get("level", 1),
            page_start=row.get("page_start"),
            page_end=row.get("page_end"),
            objectives=row.get("objectives", []) or [],
            key_formulas=row.get("key_formulas", []) or [],
            summary=row.get("summary"),
            mastery_status=row.get("mastery_status", "not_started"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            children=[],
        )
        node_map[node.path] = node

    for node in node_map.values():
        if "." in node.path:
            # Find closest parent prefix
            parts = node.path.split(".")
            parent: SyllabusNodeResponse | None = None
            for i in range(len(parts) - 1, 0, -1):
                candidate_prefix = ".".join(parts[:i])
                if candidate_prefix in node_map:
                    parent = node_map[candidate_prefix]
                    break
            if parent is not None:
                parent.children.append(node)
            else:
                roots.append(node)
        else:
            roots.append(node)

    return roots

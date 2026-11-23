import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

LTREE_LABEL_REGEX = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")


def sanitize_ltree_path(path: str) -> str:
    """Validates and normalizes an ltree path.

    PostgreSQL ltree labels must contain only [A-Za-z0-9_] and be dot-separated.
    Empty, whitespace-only, or malformed paths raise ValueError.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("scope_path cannot be empty and must be a non-empty string")
    cleaned = path.strip()
    if not LTREE_LABEL_REGEX.match(cleaned):
        raise ValueError(
            f"Invalid ltree path: '{cleaned}'. "
            "PostgreSQL ltree labels must contain only alphanumeric "
            "characters and underscores separated by dots."
        )
    return cleaned


class ScopedLtreeRepository:
    """Repository helper enforcing PostgreSQL ltree ancestor containment (<@)

    on all curriculum and chunk queries.
    An unscoped query is impossible: `scope_path` is mandatory on all methods.
    """

    def __init__(self, pool_or_conn: Any):
        self._pool_or_conn = pool_or_conn

    def validate_scope_path(self, scope_path: str) -> str:
        return sanitize_ltree_path(scope_path)

    @asynccontextmanager
    async def _get_conn(self) -> AsyncGenerator[Any, None]:
        if callable(getattr(self._pool_or_conn, "connection", None)):
            async with self._pool_or_conn.connection() as conn:
                yield conn
        else:
            yield self._pool_or_conn

    async def query_syllabus_nodes(
        self, course_id: UUID, scope_path: str
    ) -> list[dict[str, Any]]:
        """Query syllabus_nodes restricted strictly to `scope_path` and descendants."""
        valid_path = self.validate_scope_path(scope_path)
        query = (
            "SELECT * FROM syllabus_nodes "
            "WHERE course_id = %s AND path <@ %s::ltree "
            "ORDER BY order_index ASC;"
        )
        params = (str(course_id), valid_path)
        async with self._get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                return cast(list[dict[str, Any]], rows)

    async def query_document_chunks(
        self,
        course_id: UUID,
        scope_path: str,
        search_query: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Query document_chunks restricted to `scope_path` and descendants."""
        valid_path = self.validate_scope_path(scope_path)
        params: tuple[Any, ...]
        if search_query:
            query = (
                "SELECT * FROM document_chunks "
                "WHERE course_id = %s AND syllabus_path <@ %s::ltree "
                "AND markdown ILIKE %s "
                "ORDER BY id LIMIT %s;"
            )
            params = (str(course_id), valid_path, f"%{search_query}%", limit)
        else:
            query = (
                "SELECT * FROM document_chunks "
                "WHERE course_id = %s AND syllabus_path <@ %s::ltree "
                "ORDER BY id LIMIT %s;"
            )
            params = (str(course_id), valid_path, limit)

        async with self._get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall()
                return cast(list[dict[str, Any]], rows)

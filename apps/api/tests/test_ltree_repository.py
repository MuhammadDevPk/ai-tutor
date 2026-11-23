from uuid import uuid4

import pytest

from app.db.ltree_repository import ScopedLtreeRepository, sanitize_ltree_path


class FakeCursor:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.last_query = ""
        self.last_params = ()

    async def execute(self, query: str, params: tuple = ()):
        self.last_query = query
        self.last_params = params

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict] | None = None):
        self.rows = rows or []
        self.cursor_obj = FakeCursor(self.rows)

    def cursor(self):
        return self._CursorContext(self.cursor_obj)

    class _CursorContext:
        def __init__(self, cur):
            self.cur = cur

        async def __aenter__(self):
            return self.cur

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass


class FakePool:
    def __init__(self, conn: FakeConnection):
        self.conn = conn

    def connection(self):
        return self._ConnContext(self.conn)

    class _ConnContext:
        def __init__(self, conn):
            self.conn = conn

        async def __aenter__(self):
            return self.conn

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass


def test_sanitize_ltree_path_valid():
    assert sanitize_ltree_path("ch01") == "ch01"
    assert sanitize_ltree_path("ch01.t02_mean.s01") == "ch01.t02_mean.s01"
    assert sanitize_ltree_path("STA301.CH01.TOPIC_1") == "STA301.CH01.TOPIC_1"


def test_sanitize_ltree_path_invalid():
    with pytest.raises(ValueError, match="Invalid ltree path"):
        sanitize_ltree_path("ch01; DROP TABLE")
    with pytest.raises(ValueError, match="Invalid ltree path"):
        sanitize_ltree_path("ch01-topic")  # hyphens not allowed in ltree label
    with pytest.raises(ValueError, match="cannot be empty"):
        sanitize_ltree_path("")
    with pytest.raises(ValueError, match="cannot be empty"):
        sanitize_ltree_path("   ")


@pytest.mark.asyncio
async def test_chapter_1_scope_returns_chapter_1_rows():
    """(a) Chapter 1 scope returns Chapter 1 rows and enforces ltree operator."""
    mock_rows = [
        {"id": uuid4(), "path": "ch01", "title": "Chapter 1"},
        {"id": uuid4(), "path": "ch01.t01", "title": "Topic 1.1"},
        {"id": uuid4(), "path": "ch01.t01.s01", "title": "Subtopic 1.1.1"},
    ]
    conn = FakeConnection(mock_rows)
    repo = ScopedLtreeRepository(conn)
    course_id = uuid4()

    nodes = await repo.query_syllabus_nodes(course_id=course_id, scope_path="ch01")

    assert len(nodes) == 3
    assert all("ch01" in r["path"] for r in nodes)
    # Verify that <@ ltree ancestor operator was used in the SQL query
    assert "<@" in conn.cursor_obj.last_query
    assert "path <@ %s::ltree" in conn.cursor_obj.last_query
    assert conn.cursor_obj.last_params == (str(course_id), "ch01")


@pytest.mark.asyncio
async def test_chapter_1_scope_excludes_chapter_2_even_with_matching_text():
    """(b) Chapter 1 scope returns ZERO Chapter 2 rows even when chunk text matches."""
    # Suppose both Chapter 1 and Chapter 2 match "Bayes Theorem".
    # Under Chapter 1 scope, SQL executes with syllabus_path <@ %s::ltree (ch01).
    mock_rows = [
        {
            "id": uuid4(),
            "syllabus_path": "ch01.t02",
            "markdown": "Introduction to Bayes Theorem in probability.",
        }
    ]
    conn = FakeConnection(mock_rows)
    repo = ScopedLtreeRepository(conn)
    course_id = uuid4()

    chunks = await repo.query_document_chunks(
        course_id=course_id,
        scope_path="ch01",
        search_query="Bayes Theorem",
    )

    assert len(chunks) == 1
    assert chunks[0]["syllabus_path"] == "ch01.t02"
    # Ensure query enforces syllabus_path <@ %s::ltree
    assert "syllabus_path <@ %s::ltree" in conn.cursor_obj.last_query
    assert conn.cursor_obj.last_params[1] == "ch01"
    assert "%Bayes Theorem%" in conn.cursor_obj.last_params[2]


@pytest.mark.asyncio
async def test_subtopic_scope_narrows_correctly():
    """(c) Subtopic scope narrows correctly to only descendants of that subtopic."""
    mock_rows = [
        {"id": uuid4(), "path": "ch01.t01.s01", "title": "Subtopic 1.1.1"},
    ]
    conn = FakeConnection(mock_rows)
    repo = ScopedLtreeRepository(conn)
    course_id = uuid4()

    nodes = await repo.query_syllabus_nodes(
        course_id=course_id, scope_path="ch01.t01.s01"
    )

    assert len(nodes) == 1
    assert nodes[0]["path"] == "ch01.t01.s01"
    assert conn.cursor_obj.last_params == (str(course_id), "ch01.t01.s01")


def test_unscoped_call_is_impossible():
    """(d) An unscoped call is impossible through the helper API."""
    conn = FakeConnection()
    repo = ScopedLtreeRepository(conn)
    course_id = uuid4()

    # 1. Missing scope_path argument raises TypeError
    with pytest.raises(TypeError):
        repo.query_syllabus_nodes(course_id=course_id)  # type: ignore

    with pytest.raises(TypeError):
        repo.query_document_chunks(course_id=course_id)  # type: ignore

    # 2. None scope_path raises ValueError
    with pytest.raises(ValueError, match="scope_path cannot be empty"):
        repo.validate_scope_path(None)  # type: ignore

    # 3. Empty or whitespace scope_path raises ValueError
    with pytest.raises(ValueError, match="scope_path cannot be empty"):
        repo.validate_scope_path("")

    with pytest.raises(ValueError, match="scope_path cannot be empty"):
        repo.validate_scope_path("   ")

    # 4. Malformed/injected scope_path raises ValueError
    with pytest.raises(ValueError, match="Invalid ltree path"):
        repo.validate_scope_path("ch01; DROP TABLE users;")

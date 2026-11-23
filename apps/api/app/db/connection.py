from collections.abc import AsyncGenerator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

_db_pool: AsyncConnectionPool | None = None


def get_db_pool() -> AsyncConnectionPool:
    global _db_pool
    if _db_pool is None:
        _db_pool = AsyncConnectionPool(
            conninfo=settings.DATABASE_URL,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )
    return _db_pool


async def init_db_pool() -> AsyncConnectionPool:
    pool = get_db_pool()
    if pool.closed:
        await pool.open()
    return pool


async def close_db_pool() -> None:
    global _db_pool
    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None


async def get_db_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    pool = get_db_pool()
    if pool.closed:
        await pool.open()
    async with pool.connection() as conn:
        yield conn

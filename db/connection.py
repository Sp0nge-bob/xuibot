"""Единое SQLite-соединение (WAL) — без connect на каждый запрос."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite

DB_PATH = os.getenv("DB_PATH", "data/bot.db")

_conn: aiosqlite.Connection | None = None
_lock = asyncio.Lock()

os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)


async def _apply_pragmas(db: aiosqlite.Connection) -> None:
    for statement in ("PRAGMA journal_mode=WAL", "PRAGMA busy_timeout=30000",
                      "PRAGMA foreign_keys=ON", "PRAGMA synchronous=NORMAL",
                      "PRAGMA temp_store=MEMORY", "PRAGMA cache_size=-32000"):
        async with db.execute(statement) as cursor:
            await cursor.fetchall()


async def init_connection() -> None:
    global _conn
    if _conn is not None:
        return
    _conn = await aiosqlite.connect(DB_PATH, timeout=30.0)
    await _apply_pragmas(_conn)
    _conn.row_factory = aiosqlite.Row


async def close_connection() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    if _conn is None:
        await init_connection()
    async with _lock:
        yield _conn

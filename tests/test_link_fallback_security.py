"""Real isolated SQLite tests for the fallback's account-link transaction."""
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
import uuid

import aiosqlite
import pytest
import pytest_asyncio

from services import website_client
from utils.utc import utc_now


@pytest_asyncio.fixture
async def link_db(monkeypatch):
    root = Path(__file__).resolve().parents[1] / ".test_tmp"
    root.mkdir(exist_ok=True)
    path = root / f"link_security_{uuid.uuid4().hex}.db"
    async with aiosqlite.connect(path) as db:
        await db.executescript("""
            CREATE TABLE telegram_link_tokens (token TEXT PRIMARY KEY, email TEXT, expires_at TEXT, used INTEGER DEFAULT 0);
            CREATE TABLE email_accounts (email TEXT PRIMARY KEY, tg_id INTEGER, is_blocked INTEGER DEFAULT 0);
            CREATE TABLE email_blacklist (email TEXT PRIMARY KEY);
            CREATE TABLE users (tg_id INTEGER PRIMARY KEY, email TEXT);
            CREATE TABLE subscriptions (id INTEGER PRIMARY KEY, tg_id INTEGER, email_account TEXT);
            INSERT INTO users VALUES (11, NULL);
            INSERT INTO users VALUES (22, NULL);
            INSERT INTO email_accounts VALUES ('target@example.invalid', NULL, 0);
            INSERT INTO subscriptions VALUES (1, NULL, 'target@example.invalid');
        """)
        await db.execute("INSERT INTO telegram_link_tokens VALUES (?, ?, ?, 0)", (
            "synthetic-link-token", "target@example.invalid", (utc_now() + timedelta(minutes=5)).isoformat()))
        await db.commit()

    @asynccontextmanager
    async def get_db():
        async with aiosqlite.connect(path, timeout=2) as db:
            yield db

    monkeypatch.setattr("db.connection.get_db", get_db)
    monkeypatch.setattr(website_client, "get_candidate_base_urls", lambda: [])
    try:
        yield get_db
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict_sql", [
    "UPDATE email_accounts SET tg_id=22",
    "INSERT INTO email_accounts VALUES ('other@example.invalid', 11, 0)",
    "UPDATE users SET email='other@example.invalid' WHERE tg_id=11",
    "UPDATE subscriptions SET tg_id=22",
    "INSERT INTO subscriptions VALUES (2, 11, 'other@example.invalid')",
])
async def test_bot006_conflicting_links_rejected_without_consuming_token(link_db, conflict_sql):
    async with link_db() as db:
        await db.execute(conflict_sql)
        await db.commit()
        async with db.execute("SELECT id, tg_id, email_account FROM subscriptions ORDER BY id") as cursor:
            before = await cursor.fetchall()
    result = await website_client.link_telegram_token("synthetic-link-token", 11)
    assert result["ok"] is False
    async with link_db() as db:
        async with db.execute("SELECT used FROM telegram_link_tokens") as cursor:
            assert await cursor.fetchone() == (0,)
        async with db.execute("SELECT id, tg_id, email_account FROM subscriptions ORDER BY id") as cursor:
            assert await cursor.fetchall() == before


@pytest.mark.asyncio
async def test_bot006_blacklist_failure_fails_closed(link_db):
    async with link_db() as db:
        await db.execute("DROP TABLE email_blacklist")
        await db.commit()
    result = await website_client.link_telegram_token("synthetic-link-token", 11)
    assert result["ok"] is False
    async with link_db() as db:
        async with db.execute("SELECT used FROM telegram_link_tokens") as cursor:
            assert await cursor.fetchone() == (0,)


@pytest.mark.asyncio
async def test_bot006_token_has_single_winner_across_connections(link_db):
    import asyncio
    results = await asyncio.gather(*(
        website_client.link_telegram_token("synthetic-link-token", tg_id) for tg_id in (11, 22)))
    assert sum(bool(result["ok"]) for result in results) == 1
    winner = (11, 22)[next(i for i, result in enumerate(results) if result["ok"])]
    async with link_db() as db:
        async with db.execute("SELECT tg_id FROM email_accounts") as cursor:
            assert await cursor.fetchone() == (winner,)
        async with db.execute("SELECT tg_id FROM subscriptions") as cursor:
            assert await cursor.fetchone() == (winner,)


@pytest.mark.asyncio
@pytest.mark.parametrize("website_first", [False, True])
async def test_bot006_bot_init_provides_compatible_blacklist_without_website(monkeypatch, website_first):
    from unittest.mock import AsyncMock
    from db import connection, database, xui_nodes
    root = Path(__file__).resolve().parents[1] / ".test_tmp"
    root.mkdir(exist_ok=True)
    path = root / f"init_link_{uuid.uuid4().hex}.db"
    await connection.close_connection()
    monkeypatch.setattr(connection, "DB_PATH", str(path))
    monkeypatch.setattr(database, "DB_PATH", str(path))
    marker = root / f"init_marker_{uuid.uuid4().hex}"
    monkeypatch.setattr(database, "_INIT_MARKER", marker)
    monkeypatch.setattr(xui_nodes, "init_xui_nodes", AsyncMock())
    try:
        if website_first:
            async with aiosqlite.connect(path) as db:
                await db.execute("""CREATE TABLE email_blacklist (
                    email TEXT PRIMARY KEY, reason TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
                await db.execute("INSERT INTO email_blacklist(email, reason) VALUES ('blocked@example.invalid', 'test')")
                await db.commit()
        for _ in range(2):
            await database.init_db()
        async with connection.get_db() as db:
            async with db.execute("PRAGMA table_info(email_blacklist)") as cursor:
                columns = await cursor.fetchall()
            assert [(row[1], row[2], row[4], row[5]) for row in columns] == [
                ("email", "TEXT", None, 1), ("reason", "TEXT", "''", 0),
                ("created_at", "TIMESTAMP", "CURRENT_TIMESTAMP", 0),
            ]
            async with db.execute("SELECT email, reason FROM email_blacklist") as cursor:
                rows = [tuple(row) for row in await cursor.fetchall()]
            assert rows == ([("blocked@example.invalid", "test")] if website_first else [])
    finally:
        await connection.close_connection()
        marker.unlink(missing_ok=True)
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

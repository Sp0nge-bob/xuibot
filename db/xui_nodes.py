"""Реестр панелей 3x-ui (основная + вторичные ноды)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import aiosqlite

from config.settings import settings
from db.database import DB_PATH

_INIT_DONE = False


def parse_inbound_ids(raw: str) -> list[int]:
    return [int(x.strip()) for x in (raw or "").split(",") if x.strip()]


def format_inbound_ids(ids: list[int]) -> str:
    return ",".join(str(x) for x in ids)


async def init_xui_nodes() -> None:
    global _INIT_DONE
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS xui_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                host TEXT NOT NULL,
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                token TEXT DEFAULT '',
                inbound_ids TEXT NOT NULL DEFAULT '',
                is_primary INTEGER NOT NULL DEFAULT 0,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                last_sync_at TIMESTAMP,
                last_sync_error TEXT,
                is_healthy INTEGER NOT NULL DEFAULT 1,
                last_health_check_at TIMESTAMP,
                health_latency_ms INTEGER,
                last_health_error TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS node_health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms INTEGER,
                error TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(node_id) REFERENCES xui_nodes(id)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_node_health_node ON node_health_checks(node_id, checked_at)"
        )
        await db.commit()

    count = await _count_nodes()
    if count == 0:
        await _migrate_primary_from_env()
    _INIT_DONE = True


async def _ensure_init() -> None:
    if not _INIT_DONE:
        await init_xui_nodes()


async def count_nodes() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM xui_nodes") as cur:
            return (await cur.fetchone())[0]


async def _count_nodes() -> int:
    return await count_nodes()


async def _migrate_primary_from_env() -> None:
    from db.bot_settings import get_subscription_inbound_ids

    inbound_ids = await get_subscription_inbound_ids()
    await create_node(
        name="Primary",
        host=settings.XUI_HOST,
        username=settings.XUI_USERNAME or "",
        password=settings.XUI_PASSWORD or "",
        token=settings.XUI_TOKEN or "",
        inbound_ids=inbound_ids,
        is_primary=True,
        is_enabled=True,
    )


async def list_nodes(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    await _ensure_init()
    sql = "SELECT * FROM xui_nodes"
    if enabled_only:
        sql += " WHERE is_enabled = 1"
    sql += " ORDER BY is_primary DESC, sort_order ASC, id ASC"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_node(node_id: int) -> Optional[dict[str, Any]]:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM xui_nodes WHERE id = ?", (node_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_primary_node() -> Optional[dict[str, Any]]:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM xui_nodes WHERE is_primary = 1 ORDER BY id LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    if settings.XUI_HOST:
        return {
            "id": 0,
            "name": "Primary (env)",
            "host": settings.XUI_HOST,
            "username": settings.XUI_USERNAME or "",
            "password": settings.XUI_PASSWORD or "",
            "token": settings.XUI_TOKEN or "",
            "inbound_ids": settings.DEFAULT_SUBSCRIPTION_INBOUNDS or str(settings.DEFAULT_INBOUND_ID),
            "is_primary": 1,
            "is_enabled": 1,
        }
    return None


async def get_secondary_nodes(*, healthy_only: bool = False) -> list[dict[str, Any]]:
    nodes = await list_nodes(enabled_only=True)
    result = [n for n in nodes if not n.get("is_primary")]
    if healthy_only:
        result = [n for n in result if n.get("is_healthy")]
    return result


async def get_primary_inbound_ids() -> list[int]:
    primary = await get_primary_node()
    if not primary:
        return [settings.DEFAULT_INBOUND_ID]
    return parse_inbound_ids(primary.get("inbound_ids") or "")


async def create_node(
    *,
    name: str,
    host: str,
    username: str = "",
    password: str = "",
    token: str = "",
    inbound_ids: list[int],
    is_primary: bool = False,
    is_enabled: bool = True,
) -> int:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        if is_primary:
            await db.execute("UPDATE xui_nodes SET is_primary = 0")
        cursor = await db.execute(
            """INSERT INTO xui_nodes
               (name, host, username, password, token, inbound_ids,
                is_primary, is_enabled, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name.strip(),
                host.strip(),
                username,
                password,
                token,
                format_inbound_ids(inbound_ids),
                int(is_primary),
                int(is_enabled),
                await _count_nodes(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_node(node_id: int, **fields: Any) -> bool:
    await _ensure_init()
    allowed = {
        "name", "host", "username", "password", "token", "inbound_ids",
        "is_enabled", "sort_order", "last_sync_at", "last_sync_error",
        "is_healthy", "last_health_check_at", "health_latency_ms",
        "last_health_error", "consecutive_failures",
    }
    parts: list[str] = []
    values: list[Any] = []
    for key, val in fields.items():
        if key not in allowed:
            continue
        if key == "inbound_ids" and isinstance(val, list):
            val = format_inbound_ids(val)
        parts.append(f"{key} = ?")
        values.append(val)
    if not parts:
        return False
    values.append(node_id)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE xui_nodes SET {', '.join(parts)} WHERE id = ?", values)
        await db.commit()
        return True


async def set_primary_node(node_id: int) -> bool:
    await _ensure_init()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE xui_nodes SET is_primary = 0")
        cursor = await db.execute(
            "UPDATE xui_nodes SET is_primary = 1 WHERE id = ?", (node_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_node(node_id: int) -> tuple[bool, str]:
    await _ensure_init()
    node = await get_node(node_id)
    if not node:
        return False, "Нода не найдена"
    if node.get("is_primary"):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM xui_nodes WHERE is_primary = 0"
            ) as cur:
                others = (await cur.fetchone())[0]
        if others == 0:
            return False, "Нельзя удалить единственную основную ноду"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM node_health_checks WHERE node_id = ?", (node_id,))
        await db.execute("DELETE FROM xui_nodes WHERE id = ?", (node_id,))
        await db.commit()
    return True, ""


async def record_health_check(
    node_id: int,
    *,
    ok: bool,
    latency_ms: Optional[int],
    error: Optional[str],
) -> None:
    now = datetime.utcnow().isoformat()
    node = await get_node(node_id)
    if not node:
        return
    failures = 0 if ok else int(node.get("consecutive_failures") or 0) + 1
    await update_node(
        node_id,
        is_healthy=int(ok),
        last_health_check_at=now,
        health_latency_ms=latency_ms,
        last_health_error=error if not ok else None,
        consecutive_failures=failures,
    )
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO node_health_checks (node_id, ok, latency_ms, error)
               VALUES (?, ?, ?, ?)""",
            (node_id, int(ok), latency_ms, error),
        )
        await db.commit()
    await _prune_health_checks(node_id)


async def _prune_health_checks(node_id: int, keep_days: int = 7) -> None:
    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM node_health_checks WHERE node_id = ? AND checked_at < ?",
            (node_id, cutoff),
        )
        await db.commit()


async def get_uptime_24h(node_id: int) -> Optional[float]:
    """Доля успешных проверок за 24ч (0.0–1.0) или None если нет данных."""
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT COUNT(*), SUM(ok) FROM node_health_checks
               WHERE node_id = ? AND checked_at >= ?""",
            (node_id, since),
        ) as cur:
            total, ok_sum = await cur.fetchone()
    if not total:
        return None
    return round((ok_sum or 0) / total, 3)


async def nodes_summary() -> dict[str, int]:
    nodes = await list_nodes()
    enabled = [n for n in nodes if n.get("is_enabled")]
    return {
        "total": len(nodes),
        "enabled": len(enabled),
        "primary": sum(1 for n in nodes if n.get("is_primary")),
        "secondary": sum(1 for n in nodes if not n.get("is_primary")),
        "healthy": sum(1 for n in enabled if n.get("is_healthy")),
        "unhealthy": sum(1 for n in enabled if not n.get("is_healthy")),
    }
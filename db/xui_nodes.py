"""Реестр панелей 3x-ui (основная + вторичные ноды)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional


from config.settings import settings
from db.connection import get_db

_INIT_DONE = False
_INIT_IN_PROGRESS = False


def parse_inbound_ids(raw: str) -> list[int]:
    return [int(x.strip()) for x in (raw or "").split(",") if x.strip()]


def format_inbound_ids(ids: list[int]) -> str:
    return ",".join(str(x) for x in ids)


def normalize_node_host(host: str) -> str:
    h = (host or "").strip().rstrip("/")
    if h.endswith("/panel"):
        h = h[: -len("/panel")]
    return h.lower()


async def _ensure_single_primary() -> None:
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM xui_nodes ORDER BY is_primary DESC, id ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return
        keep_id = row[0]
        await db.execute("UPDATE xui_nodes SET is_primary = 0")
        await db.execute("UPDATE xui_nodes SET is_primary = 1 WHERE id = ?", (keep_id,))
        await db.commit()


async def dedupe_nodes() -> dict[str, int]:
    """Одна запись на host, одна primary. Удаляет дубликаты и health_checks."""
    async with get_db() as db:
        async with db.execute("SELECT * FROM xui_nodes ORDER BY id") as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    before = len(rows)
    if before <= 1:
        await _ensure_single_primary()
        return {"before": before, "after": before, "removed": 0}

    by_host: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = normalize_node_host(row.get("host") or "")
        if not key:
            key = f"__id_{row['id']}"
        by_host.setdefault(key, []).append(row)

    keep_ids: list[int] = []
    remove_ids: list[int] = []
    for group in by_host.values():
        group.sort(
            key=lambda r: (
                -int(r.get("is_primary") or 0),
                -(1 if (r.get("token") or "").strip() else 0),
                r["id"],
            ),
        )
        keep_ids.append(group[0]["id"])
        remove_ids.extend(r["id"] for r in group[1:])

    if remove_ids:
        async with get_db() as db:
            for rid in remove_ids:
                await db.execute(
                    "DELETE FROM node_health_checks WHERE node_id = ?", (rid,),
                )
                await db.execute("DELETE FROM xui_nodes WHERE id = ?", (rid,))
            await db.commit()
            for rid in remove_ids:
                try:
                    from services.xui import invalidate_api_cache
                    invalidate_api_cache(rid)
                except Exception:
                    pass

    await _ensure_single_primary()
    after = before - len(remove_ids)
    return {"before": before, "after": after, "removed": len(remove_ids)}


async def init_xui_nodes() -> None:
    global _INIT_DONE, _INIT_IN_PROGRESS
    if _INIT_DONE:
        return
    if _INIT_IN_PROGRESS:
        return
    _INIT_IN_PROGRESS = True
    try:
        await _init_xui_nodes_impl()
        _INIT_DONE = True
    finally:
        _INIT_IN_PROGRESS = False


async def _init_xui_nodes_impl() -> None:
    async with get_db() as db:
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
                public_available INTEGER NOT NULL DEFAULT 1,
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
        async with db.execute("PRAGMA table_info(xui_nodes)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "public_available" not in cols:
            await db.execute(
                "ALTER TABLE xui_nodes ADD COLUMN public_available INTEGER NOT NULL DEFAULT 1",
            )
        await db.commit()

    count = await _count_nodes()
    if count == 0:
        await _migrate_primary_from_env_with_retry()
    else:
        stats = await dedupe_nodes()
        if stats["removed"]:
            from loguru import logger
            logger.warning(
                "xui_nodes: удалено {} дубликатов (было {}, осталось {})",
                stats["removed"], stats["before"], stats["after"],
            )
        await _sync_primary_from_env()


async def _ensure_init() -> None:
    if not _INIT_DONE:
        await init_xui_nodes()


async def count_nodes() -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) FROM xui_nodes") as cur:
            return (await cur.fetchone())[0]


async def _count_nodes() -> int:
    return await count_nodes()


async def _migrate_primary_from_env_with_retry() -> None:
    import asyncio

    from loguru import logger

    for attempt in range(1, 9):
        try:
            await _migrate_primary_from_env()
            return
        except Exception as e:
            msg = str(e).lower()
            if await _count_nodes() > 0:
                return
            if "уже зарегистрирована" in str(e):
                return
            if "locked" in msg and attempt < 8:
                delay = min(2.0 * attempt, 10.0)
                logger.warning(
                    "Primary node migrate locked, retry {}/8 in {:.0f}s",
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise


async def _host_exists_in_nodes(host: str) -> bool:
    key = normalize_node_host(host)
    if not key:
        return False
    async with get_db() as db:
        async with db.execute("SELECT host FROM xui_nodes") as cur:
            rows = await cur.fetchall()
    return any(normalize_node_host(r[0] or "") == key for r in rows)


async def _migrate_primary_from_env() -> None:
    from db.bot_settings import get_subscription_inbound_ids_from_settings

    host = (settings.XUI_HOST or "").strip()
    if host and await _host_exists_in_nodes(host):
        return

    inbound_ids = await get_subscription_inbound_ids_from_settings()
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


async def _sync_primary_from_env() -> None:
    """При старте: подтянуть XUI_HOST и учётные данные в ★ основную ноду из .env."""
    from loguru import logger
    from services.xui import invalidate_api_cache, normalize_xui_host

    env_host_raw = (settings.XUI_HOST or "").strip()
    if not env_host_raw:
        return

    primary = await get_primary_node()
    primary_id = int((primary or {}).get("id") or 0)
    if primary_id <= 0:
        return

    env_host = normalize_xui_host(env_host_raw)
    current_host = normalize_node_host(primary.get("host") or "")
    env_username = settings.XUI_USERNAME or ""
    env_password = settings.XUI_PASSWORD or ""
    env_token = settings.XUI_TOKEN or ""
    current_username = primary.get("username") or ""
    current_password = primary.get("password") or ""
    current_token = primary.get("token") or ""

    host_changed = current_host != normalize_node_host(env_host)
    creds_changed = (
        current_username != env_username
        or current_password != env_password
        or current_token != env_token
    )
    if not host_changed and not creds_changed:
        return

    if host_changed:
        existing = await get_node_by_host(env_host_raw)
        if existing and int(existing["id"]) != primary_id:
            ok, err = await set_primary_node(existing["id"])
            if ok:
                logger.info(
                    "xui_nodes: ★ primary переключена на [{}] ({}) — был {}",
                    existing.get("name"),
                    normalize_node_host(existing.get("host") or ""),
                    current_host,
                )
                invalidate_api_cache(primary_id)
                invalidate_api_cache(existing["id"])
                primary_id = int(existing["id"])
            else:
                logger.warning("xui_nodes: не удалось переключить primary: {}", err)
                return
        else:
            await update_node(
                primary_id,
                host=env_host,
                username=env_username,
                password=env_password,
                token=env_token,
            )
            logger.info(
                "xui_nodes: ★ primary host обновлён из .env: {} → {}",
                current_host,
                normalize_node_host(env_host),
            )
            invalidate_api_cache(primary_id)
            return

    if creds_changed:
        await update_node(
            primary_id,
            username=env_username,
            password=env_password,
            token=env_token,
        )
        logger.info("xui_nodes: ★ primary учётные данные обновлены из .env")
        invalidate_api_cache(primary_id)


async def list_nodes(*, enabled_only: bool = False) -> list[dict[str, Any]]:
    await _ensure_init()
    sql = "SELECT * FROM xui_nodes"
    if enabled_only:
        sql += " WHERE is_enabled = 1"
    sql += " ORDER BY is_primary DESC, sort_order ASC, id ASC"
    async with get_db() as db:
        async with db.execute(sql) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_node_by_host(host: str) -> Optional[dict[str, Any]]:
    await _ensure_init()
    key = normalize_node_host(host)
    if not key:
        return None
    for node in await list_nodes():
        if normalize_node_host(node.get("host") or "") == key:
            return node
    return None


async def get_node(node_id: int) -> Optional[dict[str, Any]]:
    await _ensure_init()
    async with get_db() as db:
        async with db.execute("SELECT * FROM xui_nodes WHERE id = ?", (node_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_primary_node() -> Optional[dict[str, Any]]:
    await _ensure_init()
    async with get_db() as db:
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
            "inbound_ids": format_inbound_ids(settings.subscription_inbound_ids()),
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
        return settings.subscription_inbound_ids()
    return parse_inbound_ids(primary.get("inbound_ids") or "")


async def create_node(
    *,
    name: str,
    host: str,
    username: str = "",
    password: str = "",
    token: str = "",
    inbound_ids: list[int] | None = None,
    is_primary: bool = False,
    is_enabled: bool = True,
) -> int:
    await _ensure_init()
    host = host.strip()
    ids = inbound_ids or []
    if is_primary and not ids:
        raise ValueError("Для основной ноды укажите inbound IDs подписки")
    if await get_node_by_host(host):
        raise ValueError("Нода с таким host уже зарегистрирована")
    sort_order = await _count_nodes()
    async with get_db() as db:
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
                format_inbound_ids(ids),
                int(is_primary),
                int(is_enabled),
                sort_order,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def update_node(node_id: int, **fields: Any) -> bool:
    await _ensure_init()
    if "host" in fields:
        other = await get_node_by_host(str(fields["host"]))
        if other and other["id"] != node_id:
            raise ValueError("Нода с таким host уже существует")
    allowed = {
        "name", "host", "username", "password", "token", "inbound_ids",
        "is_enabled", "sort_order", "last_sync_at", "last_sync_error",
        "is_healthy", "last_health_check_at", "health_latency_ms",
        "last_health_error", "consecutive_failures", "public_available",
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
    async with get_db() as db:
        await db.execute(f"UPDATE xui_nodes SET {', '.join(parts)} WHERE id = ?", values)
        await db.commit()
        return True


async def set_node_bot_bound(node_id: int, *, bound: bool) -> tuple[bool, str]:
    """Привязка бота к панели (is_enabled). Не отключает саму панель 3x-ui."""
    node = await get_node(node_id)
    if not node:
        return False, "Нода не найдена"
    if node.get("is_primary") and not bound:
        return False, (
            "Нельзя отвязать бота от ★ основной ноды.\n"
            "Сначала назначьте другую ноду основной."
        )
    await update_node(node_id, is_enabled=int(bound))
    try:
        from services.xui import invalidate_api_cache
        invalidate_api_cache(node_id)
    except Exception:
        pass
    return True, ""


async def set_primary_node(node_id: int) -> tuple[bool, str]:
    await _ensure_init()
    node = await get_node(node_id)
    if not node:
        return False, "Нода не найдена"
    if not parse_inbound_ids(node.get("inbound_ids") or ""):
        return False, "Сначала укажите inbound IDs подписки на этой ноде (редактирование)"
    async with get_db() as db:
        await db.execute("UPDATE xui_nodes SET is_primary = 0")
        cursor = await db.execute(
            "UPDATE xui_nodes SET is_primary = 1 WHERE id = ?", (node_id,),
        )
        await db.commit()
    if cursor.rowcount > 0:
        from db.bot_settings import set_subscription_inbound_ids
        await set_subscription_inbound_ids(parse_inbound_ids(node["inbound_ids"]))
        return True, ""
    return False, "Не удалось назначить основную"


async def delete_node(node_id: int) -> tuple[bool, str]:
    await _ensure_init()
    node = await get_node(node_id)
    if not node:
        return False, "Нода не найдена"
    if node.get("is_primary"):
        async with get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) FROM xui_nodes WHERE is_primary = 0"
            ) as cur:
                others = (await cur.fetchone())[0]
        if others == 0:
            return False, "Нельзя удалить единственную основную ноду"
    async with get_db() as db:
        await db.execute("DELETE FROM node_health_checks WHERE node_id = ?", (node_id,))
        await db.execute("DELETE FROM xui_nodes WHERE id = ?", (node_id,))
        await db.commit()
    try:
        from services.xui import invalidate_api_cache
        invalidate_api_cache(node_id)
    except Exception:
        pass
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
    async with get_db() as db:
        await db.execute(
            """INSERT INTO node_health_checks (node_id, ok, latency_ms, error)
               VALUES (?, ?, ?, ?)""",
            (node_id, int(ok), latency_ms, error),
        )
        await db.commit()
    await _prune_health_checks(node_id)


async def _prune_health_checks(node_id: int, keep_days: int = 7) -> None:
    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    async with get_db() as db:
        await db.execute(
            "DELETE FROM node_health_checks WHERE node_id = ? AND checked_at < ?",
            (node_id, cutoff),
        )
        await db.commit()


async def get_uptime_24h(node_id: int) -> Optional[float]:
    """Доля успешных проверок за 24ч (0.0–1.0) или None если нет данных."""
    since = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    async with get_db() as db:
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
    unique_hosts = len({normalize_node_host(n.get("host") or "") for n in nodes if n.get("host")})
    return {
        "total": len(nodes),
        "unique_hosts": unique_hosts,
        "enabled": len(enabled),
        "primary": sum(1 for n in nodes if n.get("is_primary")),
        "secondary": sum(1 for n in nodes if not n.get("is_primary")),
        "healthy": sum(1 for n in enabled if n.get("is_healthy")),
        "unhealthy": sum(1 for n in enabled if not n.get("is_healthy")),
    }
"""Синхронизация нод: БД ↔ основная ↔ вторичные."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from services.xui import (
    _client_needs_replica_update,
    _dedupe_nodes_by_host,
    _unified_get_client_info,
    _unified_update_client,
    ensure_bot_group_on_node,
    ensure_client_absent_on_primary,
    get_api,
    get_api_for_node,
    list_bot_client_emails_on_panel,
    provision_client,
    purge_client_on_secondaries,
    remove_bot_client_on_panel,
    sub_desired_state_from_db,
    sync_client_state_on_node,
)

_secondary_sync_queue: asyncio.Queue[int] | None = None
_secondary_workers_started = False
_secondary_shutdown = asyncio.Event()
_secondary_worker_tasks: list[asyncio.Task[Any]] = []


def _get_secondary_sync_queue() -> asyncio.Queue[int]:
    global _secondary_sync_queue
    if _secondary_sync_queue is None:
        _secondary_sync_queue = asyncio.Queue()
    return _secondary_sync_queue


async def _get_primary_client_state(email: str) -> dict[str, Any] | None:
    """Состояние клиента на основной — источник истины для вторичных."""
    api = await get_api()
    info = await _unified_get_client_info(api, email)
    if info is None:
        return None
    client, _, _ = info
    return {
        "sub_id": client.sub_id or "",
        "expiry_ms": int(client.expiry_time or 0),
        "total_gb": int(client.total_gb or 0),
        "enable": bool(client.enable),
    }


async def _purge_orphan_bot_clients_on_primary(db_emails: set[str]) -> int:
    """Лишние tg/tgfree на основной, которых нет среди активных подписок в БД."""
    api = await get_api()
    on_panel = await list_bot_client_emails_on_panel(api)
    extras = on_panel - db_emails
    purged = 0
    for email in sorted(extras):
        try:
            await remove_bot_client_on_panel(api, email)
            purged += 1
            logger.info("Sync primary: удалён лишний {} (нет в БД)", email)
        except Exception as e:
            logger.error("Sync primary: не удалось удалить лишний {}: {}", email, e)
    return purged


async def ensure_subscription_on_primary(sub: dict[str, Any]) -> str:
    """
    БД → основная:
    - клиент на основной → expiry/трафик из БД;
    - клиента нет → проверить вторичные, удалить призрака, clients/add на основной.
    """
    state = sub_desired_state_from_db(sub)
    email = sub["client_email"]
    api = await get_api()
    await ensure_bot_group_on_node(api, int((await nodes_db.get_primary_node() or {}).get("id") or 0))

    info = await _unified_get_client_info(api, email)
    if info is None:
        ghost_nodes = await purge_client_on_secondaries(email)
        if ghost_nodes:
            logger.info(
                "Sync primary: {} нет на основной — удалены призраки на {}",
                email, ", ".join(ghost_nodes),
            )
        await ensure_client_absent_on_primary(email)

        traffic_gb = int(sub.get("traffic_limit_gb") or 0)
        try:
            await provision_client(
                tg_id=sub["tg_id"],
                plan_days=1,
                traffic_gb=traffic_gb,
                sub_id=sub.get("sub_id"),
                target_expiry_ms=state["expiry_ms"],
                client_email=email,
                skip_preclean=True,
            )
        except ValueError as e:
            logger.error("Sync primary: не удалось создать {}: {}", email, e)
            return "failed"
        logger.info("Sync primary: создан {} на основной из БД", email)
        return "created"

    client, _, _ = info
    if _client_needs_replica_update(
        client,
        expiry_ms=state["expiry_ms"],
        total_gb=state["total_gb"],
        sub_id=state["sub_id"],
        enable=state["enable"],
    ):
        await _unified_update_client(
            api,
            client,
            expiryTime=state["expiry_ms"],
            totalGB=state["total_gb"],
            subId=state["sub_id"] or client.sub_id or "",
            enable=state["enable"],
        )
        logger.info("Sync primary: обновлён {} (expiry/трафик из БД)", email)
        return "updated"

    logger.info("Sync primary: {} skipped (совпадает с БД)", email)
    return "skipped"


async def _sync_primary_from_db(subs: list[dict[str, Any]]) -> dict[str, int]:
    db_emails = {str(s["client_email"]).lower() for s in subs}
    orphans = await _purge_orphan_bot_clients_on_primary(db_emails)

    stats = {
        "subs": len(subs),
        "orphans_purged": orphans,
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(sub: dict) -> None:
        async with sem:
            try:
                action = await ensure_subscription_on_primary(sub)
                stats[action if action in stats else "skipped"] += 1
            except Exception as e:
                stats["failed"] += 1
                logger.error("Primary sync failed for sub #{}: {}", sub.get("id"), e)

    await asyncio.gather(*[_one(sub) for sub in subs])
    return stats


async def sync_client_on_secondary_from_primary(
    node: dict[str, Any],
    email: str,
    primary_state: dict[str, Any],
) -> dict[str, Any]:
    """Вторичная: выровнять expiry/трафик по основной (быстрая проверка)."""
    node_id = node["id"]
    try:
        api = await get_api_for_node(node)
        await ensure_bot_group_on_node(api, node_id)
        action = await sync_client_state_on_node(
            api,
            node=node,
            email=email,
            sub_id=primary_state["sub_id"],
            expiry_ms=primary_state["expiry_ms"],
            total_gb=primary_state["total_gb"],
            enable=primary_state["enable"],
        )
        return {"node_id": node_id, "email": email, "ok": True, "action": action}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
        await nodes_db.update_node(node_id, last_sync_error=err)
        logger.error("Secondary sync {} → {}: {}", email, node.get("name"), err)
        return {"node_id": node_id, "email": email, "ok": False, "error": err}


async def _sync_secondaries_from_primary(
    subs: list[dict[str, Any]],
    *,
    primary_emails: set[str],
) -> dict[str, int]:
    """
    Быстрая проверка вторичных:
    - призраки (нет на основной) → удалить;
    - для клиентов с основной → expiry/трафик как на основной.
    """
    nodes = _dedupe_nodes_by_host(await nodes_db.get_secondary_nodes(healthy_only=True))
    stats = {"nodes": len(nodes), "synced": 0, "missing": 0, "purged": 0, "failed": 0}
    if not nodes:
        return stats

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    stats_lock = asyncio.Lock()
    subs_on_primary = [
        s for s in subs if str(s["client_email"]).lower() in primary_emails
    ]

    async def _one_node(node: dict) -> None:
        node_id = node["id"]
        node_purged = 0
        node_synced = 0
        node_missing = 0
        node_failed = 0
        try:
            api = await get_api_for_node(node)
            secondary_emails = await list_bot_client_emails_on_panel(api)
            ghosts = secondary_emails - primary_emails
            logger.info(
                "Sync secondary {}: {} tg на ноде, {} на основной, призраков {}",
                node.get("name"), len(secondary_emails), len(primary_emails), len(ghosts),
            )
            for email in sorted(ghosts):
                async with sem:
                    try:
                        await remove_bot_client_on_panel(api, email)
                        node_purged += 1
                        logger.info(
                            "Sync secondary {}: удалён призрак {} (нет на основной)",
                            node.get("name"), email,
                        )
                    except Exception as e:
                        node_failed += 1
                        logger.error(
                            "Sync secondary {}: не удалось удалить {}: {}",
                            node.get("name"), email, e,
                        )

            for sub in subs_on_primary:
                email = sub["client_email"]
                primary_state = await _get_primary_client_state(email)
                if not primary_state:
                    continue
                async with sem:
                    r = await sync_client_on_secondary_from_primary(node, email, primary_state)
                    if not r.get("ok"):
                        node_failed += 1
                        continue
                    if r.get("action") == "missing":
                        node_missing += 1
                    elif r.get("action") == "updated":
                        node_synced += 1

            await nodes_db.update_node(
                node_id,
                last_sync_at=datetime.utcnow().isoformat(),
                last_sync_error=None,
            )
        except Exception as e:
            node_failed += 1
            err = f"{type(e).__name__}: {e}"[:200]
            await nodes_db.update_node(node_id, last_sync_error=err)
            logger.error("Secondary sync failed for node {}: {}", node_id, e)

        async with stats_lock:
            stats["purged"] += node_purged
            stats["synced"] += node_synced
            stats["missing"] += node_missing
            stats["failed"] += node_failed

    await asyncio.gather(*[_one_node(n) for n in nodes])
    return stats


async def run_full_nodes_sync() -> dict[str, Any]:
    """
    1) Основная ↔ БД (лишние tg удалить, недостающие создать)
    2) Вторичные ↔ основная (призраки + expiry с основной)
    """
    subs = await db.get_all_active_subscriptions()
    logger.info("Full nodes sync: {} active subscriptions in DB", len(subs))

    phase1 = await _sync_primary_from_db(subs)

    primary = await nodes_db.get_primary_node()
    if not primary:
        logger.warning("Full nodes sync: primary node not configured")
        return {"phase1": phase1, "phase2": {"nodes": 0, "synced": 0, "purged": 0, "failed": 0}}

    api_primary = await get_api_for_node(primary)
    primary_emails = await list_bot_client_emails_on_panel(api_primary)
    logger.info(
        "Full nodes sync: {} tg on primary after phase 1, {} active subs in DB",
        len(primary_emails), len(subs),
    )

    phase2 = await _sync_secondaries_from_primary(subs, primary_emails=primary_emails)

    logger.info(
        "Full nodes sync done: primary orphans={} created={} updated={} failed={}; "
        "secondary purged={} synced={} failed={}",
        phase1.get("orphans_purged", 0),
        phase1["created"], phase1["updated"], phase1["failed"],
        phase2["purged"], phase2["synced"], phase2["failed"],
    )
    return {"phase1": phase1, "phase2": phase2}


async def sync_all_secondary_nodes() -> dict[str, int]:
    """Scheduler и админка: полный цикл синхронизации."""
    result = await run_full_nodes_sync()
    p1, p2 = result["phase1"], result["phase2"]
    return {
        "subs": p1["subs"],
        "nodes": p2["nodes"],
        "ok": p2["synced"],
        "failed": p1["failed"] + p2["failed"],
        "primary_created": p1["created"],
        "primary_updated": p1["updated"],
        "primary_failed": p1["failed"],
        "primary_orphans_purged": p1.get("orphans_purged", 0),
        "secondary_failed": p2["failed"],
        "purged": p2["purged"],
        "secondary_missing": p2["missing"],
    }


async def sync_subscription_to_secondaries(sub_id: int) -> list[dict[str, Any]]:
    """После оплаты: быстрая проверка вторичных по состоянию на основной."""
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        return []

    email = sub["client_email"]
    primary_state = await _get_primary_client_state(email)
    if not primary_state:
        logger.debug(
            "Post-pay sync #{}: {} ещё не на основной — пропуск вторичных",
            sub_id, email,
        )
        return []

    nodes = await nodes_db.get_secondary_nodes(healthy_only=True)
    if not nodes:
        return []

    sem = asyncio.Semaphore(settings.XUI_SECONDARY_SYNC_WORKERS)

    async def _one(node: dict) -> dict[str, Any]:
        async with sem:
            r = await sync_client_on_secondary_from_primary(node, email, primary_state)
            if r.get("ok"):
                await nodes_db.update_node(
                    node["id"],
                    last_sync_at=datetime.utcnow().isoformat(),
                    last_sync_error=None,
                )
            return r

    return list(await asyncio.gather(*[_one(n) for n in nodes]))


async def _secondary_sync_worker() -> None:
    q = _get_secondary_sync_queue()
    while not _secondary_shutdown.is_set():
        try:
            sub_id = await asyncio.wait_for(q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        try:
            await sync_subscription_to_secondaries(sub_id)
        except Exception as e:
            logger.error("Secondary sync worker failed for #{}: {}", sub_id, e)
        finally:
            q.task_done()


async def start_secondary_sync_workers() -> None:
    global _secondary_workers_started, _secondary_worker_tasks
    if _secondary_workers_started:
        return
    _secondary_shutdown.clear()
    _secondary_workers_started = True
    workers = max(1, settings.XUI_SECONDARY_SYNC_WORKERS)
    _secondary_worker_tasks = [
        asyncio.create_task(_secondary_sync_worker(), name=f"secondary_sync_{i}")
        for i in range(workers)
    ]
    logger.info("Secondary sync workers started ({})", workers)


async def stop_secondary_sync_workers() -> None:
    global _secondary_workers_started, _secondary_worker_tasks
    if not _secondary_workers_started:
        return
    _secondary_shutdown.set()
    for task in _secondary_worker_tasks:
        task.cancel()
    if _secondary_worker_tasks:
        await asyncio.gather(*_secondary_worker_tasks, return_exceptions=True)
    _secondary_worker_tasks = []
    _secondary_workers_started = False
    logger.info("Secondary sync workers stopped")


def schedule_secondary_sync(sub_id: int) -> None:
    """Очередь после оплаты/пробного — не блокирует бота и не ломает выдачу ключа."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_get_secondary_sync_queue().put(sub_id))
    except Exception as e:
        logger.error("schedule_secondary_sync failed for #{}: {}", sub_id, e)


# обратная совместимость
async def sync_subscription_to_node(sub: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    email = sub["client_email"]
    primary_state = await _get_primary_client_state(email)
    if not primary_state:
        state = sub_desired_state_from_db(sub)
        primary_state = state
    return await sync_client_on_secondary_from_primary(node, email, primary_state)
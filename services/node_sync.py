"""Синхронизация нод: БД ↔ основная ↔ вторичные."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from services.panel_cache import panel_cache
from services.xui import (
    _client_needs_replica_update,
    _dedupe_nodes_by_host,
    _unified_get_client_info,
    _unified_update_client,
    ensure_bot_group_on_node,
    get_api,
    get_api_for_node,
    list_bot_client_emails_on_panel,
    provision_client,
    remove_bot_client_on_panel,
    get_missing_required_inbounds,
    remove_client_for_recreate,
    sub_desired_state_from_db,
    sync_client_state_on_node,
)


async def _recreate_subscription_on_primary(sub: dict[str, Any]) -> None:
    """Полное удаление на всех нодах и создание заново на основной."""
    state = sub_desired_state_from_db(sub)
    email = sub["client_email"]
    traffic_gb = int(sub.get("traffic_limit_gb") or 0)
    await remove_client_for_recreate(email)
    await asyncio.sleep(0.5)
    await provision_client(
        tg_id=sub["tg_id"],
        plan_days=1,
        traffic_gb=traffic_gb,
        sub_id=sub.get("sub_id"),
        target_expiry_ms=state["expiry_ms"],
        client_email=email,
    )


async def ensure_subscription_on_primary(sub: dict[str, Any]) -> str:
    """Фаза 1: активная подписка из БД должна быть на основной панели."""
    state = sub_desired_state_from_db(sub)
    email = sub["client_email"]
    api = await get_api()
    await ensure_bot_group_on_node(api, int((await nodes_db.get_primary_node() or {}).get("id") or 0))

    info = await _unified_get_client_info(api, email)
    if info is None:
        traffic_gb = int(sub.get("traffic_limit_gb") or 0)
        await provision_client(
            tg_id=sub["tg_id"],
            plan_days=1,
            traffic_gb=traffic_gb,
            sub_id=sub.get("sub_id"),
            target_expiry_ms=state["expiry_ms"],
            client_email=email,
        )
        logger.info("Sync primary: создан {} из БД", email)
        return "created"

    missing = await get_missing_required_inbounds(
        api, email, sub_id=state["sub_id"] or sub.get("sub_id") or "",
    )
    if missing:
        logger.warning(
            "Sync primary: {} не хватает inbounds {} — удаление на всех нодах и пересоздание",
            email, missing,
        )
        await _recreate_subscription_on_primary(sub)
        panel_cache.invalidate()
        still_missing = await get_missing_required_inbounds(
            await get_api(), email, sub_id=state["sub_id"] or sub.get("sub_id") or "",
        )
        if still_missing:
            logger.error(
                "Sync primary: {} после пересоздания всё ещё без inbounds {}",
                email, still_missing,
            )
        else:
            logger.info("Sync primary: {} пересоздан, inbounds в порядке", email)
        return "recreated"

    info = await _unified_get_client_info(api, email)
    if info is None:
        await _recreate_subscription_on_primary(sub)
        return "recreated"

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
        logger.info("Sync primary: обновлён {}", email)
        return "updated"

    from db.bot_settings import get_subscription_inbound_ids

    required = await get_subscription_inbound_ids()
    _, unified_ids, _ = info
    logger.info(
        "Sync primary: {} skipped (unified={}, required={})",
        email, sorted(set(unified_ids or [])), required,
    )
    return "skipped"


async def sync_subscription_to_node(sub: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Фаза 2: синхронизация состояния на вторичной (без создания)."""
    node_id = node["id"]
    email = sub["client_email"]
    try:
        state = sub_desired_state_from_db(sub)
        api = await get_api_for_node(node)
        await ensure_bot_group_on_node(api, node_id)
        action = await sync_client_state_on_node(
            api,
            node=node,
            email=email,
            sub_id=state["sub_id"],
            expiry_ms=state["expiry_ms"],
            total_gb=state["total_gb"],
            enable=state["enable"],
        )
        return {"node_id": node_id, "email": email, "ok": True, "action": action}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
        await nodes_db.update_node(node_id, last_sync_error=err)
        logger.error("Sync failed sub #{} → node {}: {}", sub.get("id"), node_id, err)
        return {"node_id": node_id, "email": email, "ok": False, "error": err}


async def _sync_primary_from_db(subs: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "subs": len(subs), "created": 0, "updated": 0,
        "recreated": 0, "skipped": 0, "failed": 0,
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


def _allowed_subscription_emails(subs: list[dict[str, Any]]) -> set[str]:
    return {
        (sub.get("client_email") or "").strip().lower()
        for sub in subs
        if (sub.get("client_email") or "").strip()
    }


async def _sync_secondaries_vs_primary(
    subs: list[dict[str, Any]],
) -> dict[str, int]:
    nodes = _dedupe_nodes_by_host(await nodes_db.get_secondary_nodes(healthy_only=True))
    stats = {"nodes": len(nodes), "synced": 0, "missing": 0, "purged": 0, "failed": 0}
    if not nodes:
        return stats

    allowed_emails = _allowed_subscription_emails(subs)
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    stats_lock = asyncio.Lock()

    async def _one_node(node: dict) -> None:
        node_id = node["id"]
        node_purged = 0
        node_synced = 0
        node_missing = 0
        node_failed = 0
        try:
            api = await get_api_for_node(node)
            secondary_emails = await list_bot_client_emails_on_panel(api)
            excess = secondary_emails - allowed_emails
            logger.info(
                "Sync secondary {}: на панели {} tg, в БД {}, лишних {}",
                node.get("name"), len(secondary_emails), len(allowed_emails), len(excess),
            )
            for email in sorted(excess):
                async with sem:
                    try:
                        await remove_bot_client_on_panel(api, email)
                        node_purged += 1
                        logger.info(
                            "Sync secondary {}: удалён лишний {} (нет в активных подписках БД)",
                            node.get("name"), email,
                        )
                    except Exception as e:
                        node_failed += 1
                        logger.error(
                            "Sync secondary {}: не удалось удалить {}: {}",
                            node.get("name"), email, e,
                        )

            for sub in subs:
                async with sem:
                    r = await sync_subscription_to_node(sub, node)
                    if not r.get("ok"):
                        node_failed += 1
                        continue
                    action = r.get("action")
                    if action == "missing":
                        node_missing += 1
                    else:
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
    Полная синхронизация (кнопка в админке):
    1) БД ↔ основная — восстановить/обновить клиентов
    2) Основная ↔ вторичные — синк состояния, удалить лишних tg на вторичных
    """
    subs = await db.get_all_active_subscriptions()
    logger.info("Full nodes sync: {} active subscriptions", len(subs))

    phase1 = await _sync_primary_from_db(subs)

    primary = await nodes_db.get_primary_node()
    if not primary:
        logger.warning("Full nodes sync: primary node not configured")
        return {"phase1": phase1, "phase2": {"nodes": 0, "synced": 0, "purged": 0, "failed": 0}}

    api_primary = await get_api_for_node(primary)
    primary_emails = await list_bot_client_emails_on_panel(api_primary)
    allowed = _allowed_subscription_emails(subs)
    logger.info(
        "Full nodes sync: {} tg on primary, {} active subs in DB",
        len(primary_emails), len(allowed),
    )

    phase2 = await _sync_secondaries_vs_primary(subs)

    logger.info(
        "Full nodes sync done: primary created={} updated={} recreated={} failed={}; "
        "secondary purged={} synced={} failed={}",
        phase1["created"], phase1["updated"], phase1.get("recreated", 0), phase1["failed"],
        phase2["purged"], phase2["synced"], phase2["failed"],
    )
    return {"phase1": phase1, "phase2": phase2}


async def sync_all_secondary_nodes() -> dict[str, int]:
    """Совместимость: scheduler и админка вызывают полную синхронизацию."""
    result = await run_full_nodes_sync()
    p1, p2 = result["phase1"], result["phase2"]
    return {
        "subs": p1["subs"],
        "nodes": p2["nodes"],
        "ok": p2["synced"],
        "failed": p1["failed"] + p2["failed"],
        "primary_created": p1["created"],
        "primary_updated": p1["updated"],
        "primary_recreated": p1.get("recreated", 0),
        "primary_failed": p1["failed"],
        "secondary_failed": p2["failed"],
        "purged": p2["purged"],
        "secondary_missing": p2["missing"],
    }


async def sync_subscription_to_secondaries(sub_id: int) -> list[dict[str, Any]]:
    """Быстрый синк одной подписки после оплаты (без purge всех нод)."""
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        return []
    try:
        await ensure_subscription_on_primary(sub)
    except Exception as e:
        logger.error("Post-pay primary ensure failed for #{}: {}", sub_id, e)

    nodes = await nodes_db.get_secondary_nodes(healthy_only=True)
    if not nodes:
        return []
    results = []
    for node in nodes:
        results.append(await sync_subscription_to_node(sub, node))
        if results[-1].get("ok"):
            await nodes_db.update_node(
                node["id"],
                last_sync_at=datetime.utcnow().isoformat(),
                last_sync_error=None,
            )
    return results


def schedule_secondary_sync(sub_id: int) -> None:
    """Fire-and-forget после оплаты/пробного."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_subscription_to_secondaries(sub_id))
    except RuntimeError:
        pass
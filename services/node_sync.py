"""Синхронизация нод: БД ↔ основная ↔ вторичные."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from utils.utc import utc_now
from services.xui import (
    delete_orphan_clients_everywhere,
    _client_needs_replica_update,
    _dedupe_nodes_by_host,
    _unified_get_client_info,
    _unified_update_client,
    ensure_bot_group_on_node,
    ensure_client_absent_on_primary,
    find_client_on_panel_by_sub_id,
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
        maxsize = max(1, int(settings.XUI_SECONDARY_SYNC_QUEUE_SIZE))
        _secondary_sync_queue = asyncio.Queue(maxsize=maxsize)
    return _secondary_sync_queue


def _client_state_from_info(info: tuple) -> dict[str, Any]:
    client, _, _ = info
    return {
        "sub_id": client.sub_id or "",
        "expiry_ms": int(client.expiry_time or 0),
        "total_gb": int(client.total_gb or 0),
        "enable": bool(client.enable),
    }


async def _get_primary_client_state(email: str) -> dict[str, Any] | None:
    """Состояние клиента на основной — источник истины для вторичных."""
    api = await get_api()
    info = await _unified_get_client_info(api, email)
    if info is None:
        return None
    return _client_state_from_info(info)


async def _batch_primary_client_states(emails: set[str]) -> dict[str, dict[str, Any]]:
    """Параллельный опрос основной ноды с семафором (без последовательного ожидания)."""
    if not emails:
        return {}
    api = await get_api()
    result: dict[str, dict[str, Any]] = {}
    concurrency = max(1, int(getattr(settings, "XUI_PANEL_CONCURRENCY", 5)))
    sem = asyncio.Semaphore(concurrency)

    async def _fetch(email: str) -> None:
        async with sem:
            info = await _unified_get_client_info(api, email)
            if info is not None:
                result[str(email).lower()] = _client_state_from_info(info)

    await asyncio.gather(*[_fetch(email) for email in emails], return_exceptions=True)
    return result


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

    from services.limit_ip import resolve_limit_ip_for_email

    desired_limit = await resolve_limit_ip_for_email(email)
    client, _, _ = info
    needs_limit = (client.limit_ip or 0) != desired_limit
    if needs_limit or _client_needs_replica_update(
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
            limitIp=desired_limit,
        )
        logger.info("Sync primary: обновлён {} (expiry/трафик из БД)", email)
        return "updated"

    logger.info("Sync primary: {} skipped (совпадает с БД)", email)
    return "skipped"


async def reconcile_subscriptions_with_panel() -> dict[str, int]:
    """
    Сверка и восстановление истинных client_email в БД по уникальному sub_id.
    Если email в БД был искажён (например при привязке аккаунта или баге переименования),
    восстанавливает имя клиента в БД в соответствии с источником истины — панелью 3x-ui.
    """
    stats = {"checked": 0, "reconciled": 0, "errors": 0}
    try:
        api = await get_api()
        subs = await db.get_all_active_subscriptions()
        logger.info("reconcile_subscriptions_with_panel: checking {} active subscriptions...", len(subs))
        for sub in subs:
            sid = (sub.get("sub_id") or "").strip()
            if not sid:
                continue
            stats["checked"] += 1
            try:
                c = await find_client_on_panel_by_sub_id(api, sid)
                if c and c.email:
                    real_email = c.email.strip()
                    db_email = str(sub.get("client_email") or "").strip()
                    if real_email.lower() != db_email.lower():
                        logger.info(
                            "Reconciliation: sub #{} DB email was '{}', but panel has '{}'. Restoring true client_email in DB.",
                            sub["id"], db_email, real_email,
                        )
                        await db.update_subscription_client_email(sub["id"], real_email)
                        sub["client_email"] = real_email
                        stats["reconciled"] += 1
                    else:
                        logger.debug("Reconciliation: sub #{} email '{}' already matches panel", sub["id"], real_email)

                    # Исправление отображаемого имени (display_name)
                    curr_disp = str(sub.get("display_name") or "").strip()
                    if real_email.startswith("tg") and curr_disp.startswith("Web ("):
                        await db.update_subscription_display_name(sub["id"], "Моя подписка")
                    elif real_email.startswith("web"):
                        if "_" in real_email:
                            base_part, suffix = real_email.rsplit("_", 1)
                            uid_part = base_part[3:]
                            if curr_disp.startswith("Web (") or not curr_disp:
                                new_disp = f"Web #{uid_part} ({suffix})"
                                await db.update_subscription_display_name(sub["id"], new_disp)
                        else:
                            uid_part = real_email[3:]
                            if curr_disp.startswith("Web (") or not curr_disp:
                                new_disp = f"Web #{uid_part}"
                                await db.update_subscription_display_name(sub["id"], new_disp)
                    elif "_" in real_email and not real_email.startswith("tg"):
                        base_email, suffix = real_email.rsplit("_", 1)
                        if suffix.isdigit():
                            if curr_disp == f"Web ({base_email})" or not curr_disp:
                                new_disp = f"Web ({base_email} #{suffix})"
                                await db.update_subscription_display_name(sub["id"], new_disp)
                else:
                    logger.warning("Reconciliation: sub #{} with sub_id='{}' not found on panel", sub["id"], sid)
            except Exception as ex:
                stats["errors"] += 1
                logger.error("Reconciliation error for sub #{}: {}", sub.get("id"), ex)
    except Exception as e:
        logger.error("reconcile_subscriptions_with_panel failed: {}", e)
    logger.info("reconcile_subscriptions_with_panel finished: {}", stats)
    return stats


async def _sync_primary_from_db(subs: list[dict[str, Any]]) -> dict[str, int]:
    # Сверка и автоматическое исправление client_email по уникальному sub_id
    await reconcile_subscriptions_with_panel()
    subs = await db.get_all_active_subscriptions()

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
            await asyncio.sleep(0.02)

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


async def _del_orphans_on_all_nodes() -> dict[str, int]:
    """clients/delOrphans на каждой включённой ноде (действует локально на панели)."""
    from db.xui_nodes import list_nodes

    nodes = _dedupe_nodes_by_host(await list_nodes(enabled_only=True))
    stats = {"nodes": len(nodes), "synced": 0, "missing": 0, "purged": 0, "failed": 0}
    if not nodes:
        return stats

    orphan_stats = await delete_orphan_clients_everywhere()
    stats["nodes"] = int(orphan_stats.get("nodes") or 0)
    stats["purged"] = int(orphan_stats.get("deleted") or 0)
    stats["failed"] = int(orphan_stats.get("failed") or 0)

    now = utc_now().isoformat()
    by_node = orphan_stats.get("by_node") or {}
    for node in nodes:
        node_id = int(node["id"])
        node_err = "delOrphans failed" if by_node.get(node_id) is None else None
        try:
            await nodes_db.update_node(
                node_id,
                last_sync_at=now,
                last_sync_error=node_err,
            )
        except Exception as e:
            logger.error("delOrphans: update_node {} failed: {}", node_id, e)

    logger.info(
        "delOrphans: удалено {} на {} нодах (ошибок {})",
        stats["purged"],
        stats["nodes"],
        stats["failed"],
    )
    return stats


async def run_full_nodes_sync() -> dict[str, Any]:
    """
    1) Деактивация сирот в БД
    2) Основная ↔ БД (лишние tg удалить, недостающие создать/обновить)
    3) delOrphans на всех включённых нодах
    """
    try:
        orphans = await db.deactivate_orphan_subscriptions()
        if orphans:
            logger.info("Full nodes sync: deactivated {} orphan subscription(s)", orphans)
    except Exception as e:
        logger.warning("Full nodes sync: deactivate_orphan_subscriptions failed: {}", e)

    subs = await db.get_all_active_subscriptions()
    logger.info("Full nodes sync: {} active subscriptions in DB", len(subs))

    phase1 = await _sync_primary_from_db(subs)

    if not await nodes_db.get_primary_node():
        logger.warning("Full nodes sync: primary node not configured")

    phase2 = await _del_orphans_on_all_nodes()

    logger.info(
        "Full nodes sync done: primary db_orphans={} created={} updated={} failed={}; "
        "delOrphans all nodes={} purged={} failed={}",
        phase1.get("orphans_purged", 0),
        phase1["created"], phase1["updated"], phase1["failed"],
        phase2["nodes"], phase2["purged"], phase2["failed"],
    )
    return {"phase1": phase1, "phase2": phase2}


def _sync_skipped_stats() -> dict[str, int]:
    return {
        "skipped": True,
        "subs": 0,
        "nodes": 0,
        "ok": 0,
        "failed": 0,
        "primary_created": 0,
        "primary_updated": 0,
        "primary_failed": 0,
        "primary_orphans_purged": 0,
        "secondary_failed": 0,
        "purged": 0,
        "secondary_missing": 0,
    }


async def sync_all_secondary_nodes(*, force: bool = False) -> dict[str, int]:
    """Полный цикл синхронизации (не delete/provision/extend).

    force=True — ручная кнопка в админке, игнорирует «автосинк выключен».
    """
    from db import bot_settings as bot_settings_db

    if not force and await bot_settings_db.is_sync_disabled():
        logger.info("Full nodes sync skipped — disabled in admin")
        return _sync_skipped_stats()

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
    """После оплаты: параметры на вторичные пушит панель 3x-ui с основной."""
    logger.debug(
        "Post-pay secondary sync #{} skipped — panel propagates from primary",
        sub_id,
    )
    return []


async def _secondary_sync_worker() -> None:
    q = _get_secondary_sync_queue()
    while not _secondary_shutdown.is_set():
        try:
            sub_id = await asyncio.wait_for(q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        try:
            from db import bot_settings as bot_settings_db
            if await bot_settings_db.is_sync_disabled():
                continue
            await sync_subscription_to_secondaries(sub_id)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Secondary sync worker failed for #{}: {}", sub_id, e)
        finally:
            q.task_done()


async def start_secondary_sync_workers() -> None:
    """Очередь после оплаты не используется — панель синхронизирует параметры с основной."""
    logger.debug("Secondary sync workers not started — panel propagates from primary")


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


async def _enqueue_secondary_sync(sub_id: int) -> None:
    """Зарезервировано: воркеры отключены — панель синхронизирует с Primary сама."""
    return


def schedule_secondary_sync(sub_id: int) -> None:
    """
    No-op: параметры клиента панель 3x-ui разносит с Primary без push с бота.
    Вызовы после оплаты оставлены для совместимости и не трогают память/панель.
    """
    del sub_id


# обратная совместимость
async def sync_subscription_to_node(sub: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    email = sub["client_email"]
    primary_state = await _get_primary_client_state(email)
    if not primary_state:
        state = sub_desired_state_from_db(sub)
        primary_state = state
    return await sync_client_on_secondary_from_primary(node, email, primary_state)
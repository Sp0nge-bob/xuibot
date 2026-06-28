"""Очистка истёкших: delDepleted на панелях + удаление неактивных записей из БД."""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import tickets as tickets_db
from services.xui import delete_depleted_clients_everywhere


async def purge_stale_expired_subscriptions() -> dict[str, Any]:
    if not settings.EXPIRED_PURGE_ENABLED:
        logger.debug("Очистка истёкших: выключена (EXPIRED_PURGE_ENABLED=false)")
        return {
            "enabled": False,
            "panel_deleted": 0,
            "panel_nodes_failed": 0,
            "subs": 0,
            "deleted": 0,
            "failed": 0,
        }

    panel_stats = await delete_depleted_clients_everywhere()
    panel_deleted = int(panel_stats.get("deleted") or 0)
    panel_failed = int(panel_stats.get("failed") or 0)
    if panel_deleted or panel_failed:
        logger.info(
            "delDepleted: нод={} удалено_клиентов={} ошибок_нод={}",
            panel_stats.get("nodes", 0),
            panel_deleted,
            panel_failed,
        )

    after_days = max(0, int(settings.EXPIRED_PURGE_AFTER_DAYS))
    subs = await db.get_stale_inactive_subscriptions(after_days=after_days)
    if not subs:
        logger.info(
            "Очистка БД: нет неактивных подписок старше {} дн. (панель: delDepleted)",
            after_days,
        )
        return {
            "enabled": True,
            "panel_deleted": panel_deleted,
            "panel_nodes_failed": panel_failed,
            "subs": 0,
            "deleted": 0,
            "failed": 0,
        }

    logger.info(
        "Очистка БД: удаляем {} неактивных подписок (end_date старше {} дн.)",
        len(subs),
        after_days,
    )
    stats = {
        "enabled": True,
        "panel_deleted": panel_deleted,
        "panel_nodes_failed": panel_failed,
        "subs": len(subs),
        "deleted": 0,
        "failed": 0,
    }
    stats_lock = asyncio.Lock()
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(sub: dict[str, Any]) -> None:
        sub_id = sub["id"]
        email = sub["client_email"]
        async with sem:
            try:
                await tickets_db.cancel_tickets_for_subscription(sub_id)
                if not await db.delete_subscription_record(sub_id):
                    logger.warning(
                        "Очистка БД: запись #{} ({}) не удалена",
                        sub_id,
                        email,
                    )
                    async with stats_lock:
                        stats["failed"] += 1
                    return
                async with stats_lock:
                    stats["deleted"] += 1
                logger.info(
                    "Очистка БД: подписка #{} удалена (tg_id={}, email={})",
                    sub_id,
                    sub["tg_id"],
                    email,
                )
            except Exception as e:
                async with stats_lock:
                    stats["failed"] += 1
                logger.error("Очистка БД: ошибка подписки #{} ({}): {}", sub_id, email, e)

    await asyncio.gather(*[_one(sub) for sub in subs])
    logger.info(
        "Очистка истёкших готова: delDepleted={} db_кандидатов={} db_удалено={} db_ошибок={}",
        panel_deleted,
        stats["subs"],
        stats["deleted"],
        stats["failed"],
    )
    return stats
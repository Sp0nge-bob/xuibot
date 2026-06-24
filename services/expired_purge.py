"""Удаление неактивных подписок и клиентов на панели, истёкших более N дней назад."""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import tickets as tickets_db
from services.xui import remove_client_everywhere


async def purge_stale_expired_subscriptions() -> dict[str, Any]:
    if not settings.EXPIRED_PURGE_ENABLED:
        logger.debug("Очистка истёкших: выключена (EXPIRED_PURGE_ENABLED=false)")
        return {"enabled": False, "subs": 0, "deleted": 0, "panel_inbounds": 0, "failed": 0}

    after_days = max(1, int(settings.EXPIRED_PURGE_AFTER_DAYS))
    subs = await db.get_stale_inactive_subscriptions(after_days=after_days)
    if not subs:
        logger.info("Очистка истёкших: нет неактивных подписок старше {} дн.", after_days)
        return {"enabled": True, "subs": 0, "deleted": 0, "panel_inbounds": 0, "failed": 0}

    logger.info(
        "Очистка истёкших: удаляем {} подписок (end_date старше {} дн.)",
        len(subs),
        after_days,
    )
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    stats = {"enabled": True, "subs": len(subs), "deleted": 0, "panel_inbounds": 0, "failed": 0}
    stats_lock = asyncio.Lock()
    panel_done: set[str] = set()
    panel_lock = asyncio.Lock()

    async def _purge_panel_once(email: str) -> int:
        async with panel_lock:
            key = email.lower()
            if key in panel_done:
                return 0
            panel_done.add(key)
        return len(await remove_client_everywhere(email))

    async def _one(sub: dict[str, Any]) -> None:
        sub_id = sub["id"]
        email = sub["client_email"]
        async with sem:
            try:
                removed = await _purge_panel_once(email)
                await tickets_db.cancel_tickets_for_subscription(sub_id)
                if not await db.delete_subscription_record(sub_id):
                    logger.warning(
                        "Очистка истёкших: запись #{} ({}) не удалена из БД",
                        sub_id,
                        email,
                    )
                    async with stats_lock:
                        stats["failed"] += 1
                    return
                async with stats_lock:
                    stats["deleted"] += 1
                    stats["panel_inbounds"] += removed
                logger.info(
                    "Очистка истёкших: подписка #{} удалена (tg_id={}, email={}, panel inbounds={})",
                    sub_id,
                    sub["tg_id"],
                    email,
                    removed or "—",
                )
            except Exception as e:
                async with stats_lock:
                    stats["failed"] += 1
                logger.error("Очистка истёкших: ошибка подписки #{} ({}): {}", sub_id, email, e)

    await asyncio.gather(*[_one(sub) for sub in subs])
    logger.info(
        "Очистка истёкших готова: кандидатов={} удалено={} failed={} panel inbounds={}",
        stats["subs"],
        stats["deleted"],
        stats["failed"],
        stats["panel_inbounds"],
    )
    return stats
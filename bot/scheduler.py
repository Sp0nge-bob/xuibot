"""
Планировщик: health нод, истечение подписок, полная синхронизация нод раз в сутки.
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import settings
from db import database as db
from services.xui import disable_client
from services.subscription_sync import sync_subscription
from services.node_sync import sync_all_secondary_nodes
from services.node_health import check_all_nodes_health

scheduler = AsyncIOScheduler()


async def check_expired_subscriptions():
    logger.info("Checking expired subscriptions...")
    expired = await db.get_expired_subscriptions()
    if not expired:
        return

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(sub: dict) -> None:
        async with sem:
            try:
                synced = await sync_subscription(sub, repair=False)
                if synced:
                    return
                await disable_client(sub["client_email"])
                await db.deactivate_subscription(sub["id"])
                logger.info("Deactivated expired subscription for tg_id={}", sub["tg_id"])
            except Exception as e:
                logger.error("Error deactivating sub {}: {}", sub["id"], e)

    await asyncio.gather(*[_one(sub) for sub in expired])


async def check_nodes_health_job():
    await check_all_nodes_health()


async def scheduled_full_nodes_sync():
    """Тот же прогон, что кнопка «Синхронизировать вторичные» в админке."""
    logger.info("Scheduled full nodes sync (every {}h)", settings.FULL_SYNC_INTERVAL_HOURS)
    try:
        stats = await sync_all_secondary_nodes()
        logger.info(
            "Scheduled sync done: subs={} nodes={} ok={} failed={} "
            "primary_created={} primary_updated={} purged={}",
            stats.get("subs", 0),
            stats.get("nodes", 0),
            stats.get("ok", 0),
            stats.get("failed", 0),
            stats.get("primary_created", 0),
            stats.get("primary_updated", 0),
            stats.get("purged", 0),
        )
    except Exception as e:
        logger.exception("Scheduled full nodes sync failed: {}", e)


def start_scheduler():
    scheduler.add_job(check_nodes_health_job, "interval", minutes=5, id="check_nodes_health")
    scheduler.add_job(
        scheduled_full_nodes_sync,
        "interval",
        hours=settings.FULL_SYNC_INTERVAL_HOURS,
        id="full_nodes_sync",
    )
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, id="check_expired")
    scheduler.start()
    logger.info(
        "Scheduler started (health 5m, full nodes sync {}h, expiry 1h)",
        settings.FULL_SYNC_INTERVAL_HOURS,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
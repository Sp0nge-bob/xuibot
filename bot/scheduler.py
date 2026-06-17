"""
Планировщик задач в процессе бота (лёгкие job'ы).
Тяжёлая синхронизация нод — в отдельном run_sync.py (раз в 24ч).
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import settings
from db import database as db
from services.xui import disable_client
from services.subscription_sync import sync_subscription
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


def start_scheduler():
    scheduler.add_job(check_nodes_health_job, "interval", minutes=5, id="check_nodes_health")
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, id="check_expired")
    scheduler.start()
    logger.info(
        "Scheduler started (health 5m, expiry 1h). "
        "Full node sync: run_sync.py every {}h",
        settings.FULL_SYNC_INTERVAL_HOURS,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
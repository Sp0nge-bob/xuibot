"""
Планировщик задач (проверка истёкших подписок).
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import settings
from db import database as db
from services.panel_cache import panel_cache
from services.xui import disable_client, get_api
from services.subscription_sync import sync_subscription

scheduler = AsyncIOScheduler()


async def sync_all_subscriptions():
    logger.info("Syncing subscriptions with 3x-ui panel...")
    active = await db.get_all_active_subscriptions()
    if not active:
        return

    api = await get_api()
    await panel_cache.refresh(api, force=True)

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _sync_one(sub: dict) -> None:
        async with sem:
            try:
                await sync_subscription(sub, repair=True)  # repair только при missing/extra
            except Exception as e:
                logger.error("Sync error for sub {}: {}", sub["id"], e)

    await asyncio.gather(*[_sync_one(sub) for sub in active])
    logger.info("Sync complete: {} subscriptions", len(active))


async def check_expired_subscriptions():
    logger.info("Checking expired subscriptions...")
    expired = await db.get_expired_subscriptions()
    for sub in expired:
        try:
            synced = await sync_subscription(sub, repair=False)
            if synced:
                continue
            await disable_client(sub["client_email"])
            await db.deactivate_subscription(sub["id"])
            logger.info("Deactivated expired subscription for tg_id={}", sub["tg_id"])
        except Exception as e:
            logger.error("Error deactivating sub {}: {}", sub["id"], e)


def start_scheduler():
    scheduler.add_job(sync_all_subscriptions, "interval", hours=6, id="sync_panel")
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, id="check_expired")
    scheduler.start()
    logger.info("Scheduler started (sync every 6h, expiry check hourly)")
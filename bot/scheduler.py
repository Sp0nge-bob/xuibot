"""
Планировщик: health нод, истечение подписок, полная синхронизация нод раз в сутки.
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import settings
from db import database as db
from services.xui import disable_client
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
                await disable_client(sub["client_email"])
                await db.deactivate_subscription(sub["id"])
                logger.info("Deactivated expired subscription for tg_id={}", sub["tg_id"])
            except Exception as e:
                logger.error("Error deactivating sub {}: {}", sub["id"], e)

    await asyncio.gather(*[_one(sub) for sub in expired])


async def expire_stale_pending_orders_job():
    count = await db.expire_stale_pending_orders(settings.STALE_PENDING_ORDER_HOURS)
    if count:
        logger.info("Expired {} stale pending orders", count)


async def check_nodes_health_job():
    await check_all_nodes_health()


async def run_full_nodes_sync(*, source: str) -> None:
    """Тот же прогон, что кнопка «Синхронизировать вторичные» в админке."""
    from db import bot_settings as bot_settings_db

    if await bot_settings_db.is_sync_disabled():
        logger.info("Full nodes sync skipped ({}) — disabled in debug", source)
        return

    logger.info("Full nodes sync ({})", source)
    try:
        stats = await sync_all_secondary_nodes()
        logger.info(
            "Full nodes sync done ({source}): subs={subs} nodes={nodes} ok={ok} failed={failed} "
            "primary_created={primary_created} primary_updated={primary_updated} purged={purged}",
            source=source,
            subs=stats.get("subs", 0),
            nodes=stats.get("nodes", 0),
            ok=stats.get("ok", 0),
            failed=stats.get("failed", 0),
            primary_created=stats.get("primary_created", 0),
            primary_updated=stats.get("primary_updated", 0),
            purged=stats.get("purged", 0),
        )
    except Exception as e:
        logger.exception("Full nodes sync failed ({source}): {}", source, e)


async def scheduled_full_nodes_sync():
    await run_full_nodes_sync(source=f"every {settings.FULL_SYNC_INTERVAL_HOURS}h")


def start_scheduler():
    scheduler.add_job(check_nodes_health_job, "interval", minutes=5, id="check_nodes_health")
    scheduler.add_job(
        scheduled_full_nodes_sync,
        "interval",
        hours=settings.FULL_SYNC_INTERVAL_HOURS,
        id="full_nodes_sync",
    )
    scheduler.add_job(check_expired_subscriptions, "interval", hours=1, id="check_expired")
    scheduler.add_job(expire_stale_pending_orders_job, "interval", hours=6, id="expire_stale_pending")
    scheduler.start()
    logger.info(
        "Scheduler started (health 5m, full nodes sync {}h, expiry 1h, stale pending 6h)",
        settings.FULL_SYNC_INTERVAL_HOURS,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
"""
Планировщик: health нод, истечение подписок, напоминания, синхронизация нод, бэкап.
"""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from config.settings import settings
from db import database as db
from services.xui import disable_client
from services.node_sync import sync_all_secondary_nodes
from services.node_alerts import process_health_transitions
from services.node_health import check_all_nodes_health
from services.primary_gate import apply_primary_health_results
from services.backup import run_scheduled_backup
from services.expiry_reminders import send_expiry_reminders
from services.expired_purge import purge_stale_expired_subscriptions

scheduler = AsyncIOScheduler()


async def heartbeat_job():
    stats = await db.get_admin_stats()
    logger.info(
        "Пульс: users={} paid_subs={} trial_subs={} paid_orders={}",
        stats.get("users", 0),
        stats.get("paid_subs", 0),
        stats.get("trial_subs", 0),
        stats.get("paid_orders", 0),
    )


async def check_expired_subscriptions():
    expired = await db.get_expired_subscriptions()
    if not expired:
        logger.info("Истечение подписок: просроченных нет")
        return

    logger.info("Истечение подписок: отключаем {}", len(expired))
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(sub: dict) -> None:
        async with sem:
            try:
                await disable_client(sub["client_email"])
                await db.deactivate_subscription(sub["id"])
                logger.info(
                    "Подписка #{} отключена (tg_id={}, email={})",
                    sub["id"],
                    sub["tg_id"],
                    sub["client_email"],
                )
            except Exception as e:
                logger.error("Ошибка отключения подписки #{}: {}", sub["id"], e)

    await asyncio.gather(*[_one(sub) for sub in expired])


async def purge_stale_expired_subscriptions_job():
    stats = await purge_stale_expired_subscriptions()
    if stats.get("enabled") and stats.get("subs"):
        logger.info(
            "Очистка истёкших (итог): удалено={} ошибок={} panel inbounds={}",
            stats.get("deleted", 0),
            stats.get("failed", 0),
            stats.get("panel_inbounds", 0),
        )


async def expire_stale_pending_orders_job():
    count = await db.expire_stale_pending_orders(settings.STALE_PENDING_ORDER_HOURS)
    if count:
        logger.info("Старые pending-заказы: помечено failed={}", count)
    else:
        logger.info("Старые pending-заказы: очистка не требуется")


async def expiry_reminder_job():
    stats = await send_expiry_reminders()
    logger.info(
        "Напоминания о сроке: отправлено={} ошибок={} подписок в окне={}",
        stats["sent"],
        stats["failed"],
        stats["subs"],
    )


async def check_nodes_health_job():
    results = await check_all_nodes_health()
    await apply_primary_health_results(results)
    await process_health_transitions(results)
    if not results:
        logger.info("Health нод: нет включённых нод")
        return
    ok = sum(1 for r in results if r.get("ok"))
    if ok == len(results):
        logger.info("Health нод: {}/{} доступны", ok, len(results))
    else:
        bad = [
            f"{r.get('name') or r.get('node_id')} ({r.get('error') or 'fail'})"
            for r in results
            if not r.get("ok")
        ]
        logger.warning("Health нод: {}/{} доступны, проблемы: {}", ok, len(results), "; ".join(bad))


async def run_full_nodes_sync(*, source: str) -> None:
    """Тот же прогон, что кнопка «Синхронизировать вторичные» в админке."""
    from db import bot_settings as bot_settings_db

    if await bot_settings_db.is_sync_disabled():
        logger.info("Синк нод пропущен ({}) — выключен в админке", source)
        return

    logger.info("Синк нод старт ({})", source)
    try:
        stats = await sync_all_secondary_nodes()
        logger.info(
            "Синк нод готов ({source}): subs={subs} nodes={nodes} ok={ok} failed={failed} "
            "created={primary_created} updated={primary_updated} purged={purged}",
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
        logger.exception("Синк нод ошибка ({source}): {}", source, e)


async def scheduled_full_nodes_sync():
    await run_full_nodes_sync(source=f"каждые {settings.FULL_SYNC_INTERVAL_HOURS}ч")


async def reschedule_backup_job() -> str | None:
    """Перечитать интервал и вкл/выкл из bot_settings, обновить задачу auto_backup."""
    from db import bot_settings as bot_settings_db

    try:
        scheduler.remove_job("auto_backup")
    except Exception:
        pass

    if not settings.BACKUP_ENABLED:
        return None
    if await bot_settings_db.is_backup_disabled():
        logger.info("Автобэкап выключен в админке — задача снята")
        return None

    interval = await bot_settings_db.get_backup_interval()
    kwargs = bot_settings_db.backup_interval_to_scheduler_kwargs(interval)
    if scheduler.running:
        scheduler.add_job(
            run_scheduled_backup,
            "interval",
            id="auto_backup",
            replace_existing=True,
            **kwargs,
        )
        logger.info(
            "Автобэкап: {} ({})",
            bot_settings_db.format_backup_interval_label(interval),
            interval,
        )
    return interval


def start_scheduler():
    heartbeat_min = max(1, int(settings.LOG_HEARTBEAT_INTERVAL_MINUTES))
    scheduler.add_job(heartbeat_job, "interval", minutes=heartbeat_min, id="heartbeat")
    scheduler.add_job(check_nodes_health_job, "interval", minutes=5, id="check_nodes_health")
    scheduler.add_job(
        scheduled_full_nodes_sync,
        "interval",
        hours=settings.FULL_SYNC_INTERVAL_HOURS,
        id="full_nodes_sync",
    )
    scheduler.add_job(
        check_expired_subscriptions,
        "interval",
        hours=settings.EXPIRED_CHECK_INTERVAL_HOURS,
        id="check_expired",
    )
    if settings.EXPIRED_PURGE_ENABLED:
        scheduler.add_job(
            purge_stale_expired_subscriptions_job,
            "interval",
            hours=settings.EXPIRED_PURGE_INTERVAL_HOURS,
            id="purge_stale_expired",
        )
    scheduler.add_job(expire_stale_pending_orders_job, "interval", hours=6, id="expire_stale_pending")
    if settings.EXPIRY_REMINDER_ENABLED:
        scheduler.add_job(
            expiry_reminder_job,
            "interval",
            hours=settings.EXPIRY_REMINDER_INTERVAL_HOURS,
            id="expiry_reminder",
        )
    scheduler.start()
    purge_label = (
        f"{settings.EXPIRED_PURGE_AFTER_DAYS}д / {settings.EXPIRED_PURGE_INTERVAL_HOURS}ч"
        if settings.EXPIRED_PURGE_ENABLED
        else "выкл"
    )
    logger.info(
        "Планировщик: пульс {}мин, health 5мин, синк {}ч, истечение {}ч, "
        "очистка истёкших {}, напоминания {}, pending 6ч, бэкап — после init → tail -f data/logs/bot.log",
        heartbeat_min,
        settings.FULL_SYNC_INTERVAL_HOURS,
        settings.EXPIRED_CHECK_INTERVAL_HOURS,
        purge_label,
        f"{settings.EXPIRY_REMINDER_INTERVAL_HOURS}ч" if settings.EXPIRY_REMINDER_ENABLED else "выкл",
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
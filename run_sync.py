"""
Фоновая полная синхронизация нод (отдельный процесс от Telegram-бота).

Запуск:
    python run_sync.py --once          # один прогон и выход
    python run_sync.py                 # демон: раз в 24ч + ручные запросы из админки

Рекомендуется на VPS:
    screen -S sync
    python run_sync.py
"""
from __future__ import annotations

import argparse
import asyncio
import time

from loguru import logger

from config.settings import settings
from db.database import init_db
from services.node_sync import run_full_nodes_sync
from services.sync_store import (
    clear_manual_request,
    get_sync_report,
    peek_manual_request,
    save_sync_error,
    save_sync_success,
    set_sync_running,
)


async def _run_full_sync() -> None:
    await set_sync_running()
    try:
        result = await run_full_nodes_sync()
        await save_sync_success(result)
        p1, p2 = result.get("phase1", {}), result.get("phase2", {})
        logger.info(
            "Full sync OK: primary created={} updated={} failed={}; "
            "secondary purged={} synced={} failed={}",
            p1.get("created", 0), p1.get("updated", 0), p1.get("failed", 0),
            p2.get("purged", 0), p2.get("synced", 0), p2.get("failed", 0),
        )
    except Exception as e:
        logger.exception("Full sync failed: {}", e)
        await save_sync_error(e)
        raise


def _interval_sec() -> float:
    return float(settings.FULL_SYNC_INTERVAL_HOURS) * 3600.0


async def _daemon_loop(poll_sec: float) -> None:
    interval = _interval_sec()
    report = await get_sync_report()
    last_scheduled = time.monotonic()
    if not report.get("finished_at"):
        logger.info("First run — no previous sync in DB")
        try:
            await _run_full_sync()
        except Exception:
            pass
        last_scheduled = time.monotonic()

    logger.info(
        "Sync daemon started (scheduled every {}h, poll {}s for manual requests)",
        settings.FULL_SYNC_INTERVAL_HOURS, int(poll_sec),
    )

    while True:
        now = time.monotonic()
        manual = await peek_manual_request()
        due = (now - last_scheduled) >= interval
        if manual and manual.strip():
            logger.info("Manual full sync requested from admin")
            try:
                await _run_full_sync()
            except Exception:
                pass
            last_scheduled = time.monotonic()
        elif due:
            logger.info("Scheduled full sync (every {}h)", settings.FULL_SYNC_INTERVAL_HOURS)
            try:
                await _run_full_sync()
            except Exception:
                pass
            last_scheduled = time.monotonic()
        await asyncio.sleep(poll_sec)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Background VPN nodes full sync")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one full sync and exit",
    )
    parser.add_argument(
        "--poll",
        type=int,
        default=60,
        help="Seconds between manual-request checks in daemon mode (default: 60)",
    )
    args = parser.parse_args()

    await init_db()

    if args.once:
        await clear_manual_request()
        await _run_full_sync()
        return

    await _daemon_loop(max(10, args.poll))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Sync daemon stopped")
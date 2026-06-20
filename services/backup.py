"""Создание архива бэкапа и отправка админам в Telegram."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiogram.types import FSInputFile
from loguru import logger

from config.settings import settings
from db import database as db
from db.connection import DB_PATH
from db import bot_settings as bot_settings_db

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"
_MAX_LOG_BYTES = 10 * 1024 * 1024


def _sqlite_backup_file(src: Path, dest: Path) -> None:
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest_conn = sqlite3.connect(dest)
    try:
        src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()


def _collect_log_paths() -> list[Path]:
    from config.logging_setup import current_log_path

    paths: list[Path] = []
    main_log = current_log_path()
    if main_log and main_log.is_file():
        paths.append(main_log)
    log_dir = Path(settings.LOG_DIR)
    if log_dir.is_dir():
        for p in sorted(log_dir.glob("botlog_*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:2]:
            if p not in paths and p.is_file():
                paths.append(p)
    return paths


async def _build_manifest() -> dict[str, Any]:
    stats = await db.get_admin_stats()
    sync_disabled = await bot_settings_db.is_sync_disabled()
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": DB_PATH,
        "stats": stats,
        "sync_disabled": sync_disabled,
        "test_mode": settings.TEST_MODE,
    }


def _restore_instructions() -> str:
    return (
        "VPN Platega Bot — восстановление из бэкапа\n"
        "=====================================\n\n"
        "1. Остановите бота (app.py и run_bot.py).\n"
        "2. Замените data/bot.db файлом bot.db из архива.\n"
        "3. Запустите бота снова.\n\n"
        "В архиве также manifest.json (статистика на момент бэкапа)\n"
        "и при наличии — последние логи в папке logs/.\n"
    )


def _prune_local_backups(retain: int) -> None:
    if retain < 1:
        return
    archives = sorted(
        _BACKUP_DIR.glob("vpn-bot-backup_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in archives[retain:]:
        try:
            old.unlink()
        except OSError as e:
            logger.warning("Failed to remove old backup {}: {}", old, e)


async def create_backup_archive() -> Path:
    """Собирает zip: bot.db (sqlite backup), manifest, restore.txt, логи."""
    src_db = Path(DB_PATH)
    if not src_db.is_file():
        raise FileNotFoundError(f"Database not found: {src_db}")

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = _BACKUP_DIR / f"vpn-bot-backup_{stamp}.zip"
    tmp_db = _BACKUP_DIR / f"_tmp_bot_{stamp}.db"

    try:
        await asyncio.to_thread(_sqlite_backup_file, src_db, tmp_db)
        manifest = await _build_manifest()

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname="bot.db")
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("restore.txt", _restore_instructions())
            for log_path in _collect_log_paths():
                if log_path.stat().st_size > _MAX_LOG_BYTES:
                    logger.debug("Skip large log in backup: {}", log_path)
                    continue
                zf.write(log_path, arcname=f"logs/{log_path.name}")

        _prune_local_backups(settings.BACKUP_LOCAL_RETAIN)
        logger.info("Backup archive created: {} ({:.1f} KB)", archive_path, archive_path.stat().st_size / 1024)
        return archive_path
    finally:
        if tmp_db.is_file():
            try:
                tmp_db.unlink()
            except OSError:
                pass


async def send_backup_to_admins(*, source: str = "manual") -> dict[str, Any]:
    """Создаёт архив и отправляет всем BOT_ADMINS. Возвращает сводку."""
    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Backup skipped ({}) — BOT_ADMINS empty", source)
        return {"ok": False, "reason": "no_admins", "sent": 0}

    archive = await create_backup_archive()
    size_kb = archive.stat().st_size / 1024
    manifest = await _build_manifest()
    stats = manifest.get("stats") or {}

    caption = (
        f"💾 <b>Бэкап бота</b> ({source})\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📅 UTC: <code>{manifest['created_at_utc'][:19]}</code>\n"
        f"📦 Размер: <b>{size_kb:.0f} KB</b>\n\n"
        f"👥 Пользователей: <b>{stats.get('users', 0)}</b>\n"
        f"✅ Платных подписок: <b>{stats.get('paid_subs', 0)}</b>\n"
        f"💰 Оплаченных заказов: <b>{stats.get('paid_orders', 0)}</b>\n\n"
        f"<i>Внутри: bot.db, manifest.json, restore.txt, логи.</i>"
    )

    import sys

    bot_mod = sys.modules.get("bot")
    if bot_mod is None:
        raise RuntimeError("Telegram bot module is not loaded")

    sent = 0
    errors: list[str] = []
    for admin_id in admin_ids:
        try:
            doc = FSInputFile(archive, filename=archive.name)
            await bot_mod.bot.send_document(admin_id, doc, caption=caption)
            sent += 1
        except Exception as e:
            logger.error("Backup send failed for admin {}: {}", admin_id, e)
            errors.append(f"{admin_id}: {e}")

    return {
        "ok": sent > 0,
        "sent": sent,
        "total": len(admin_ids),
        "archive": str(archive),
        "errors": errors,
    }


async def run_scheduled_backup() -> None:
    if not settings.BACKUP_ENABLED:
        return
    if await bot_settings_db.is_backup_disabled():
        logger.debug("Scheduled backup skipped — disabled in admin")
        return
    try:
        result = await send_backup_to_admins(source="auto")
        if result.get("ok"):
            logger.info("Scheduled backup sent to {}/{} admins", result["sent"], result["total"])
        else:
            logger.warning("Scheduled backup failed: {}", result)
    except Exception as e:
        logger.exception("Scheduled backup error: {}", e)
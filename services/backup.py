"""Создание архива бэкапа и отправка админам в Telegram."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
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
from db.xui_nodes import list_nodes
from services.test_mode import is_test_mode
from services.xui import _dedupe_nodes_by_host, get_api_for_node

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


async def _fetch_single_node_db(node: dict[str, Any], dest_dir: Path, sem: asyncio.Semaphore) -> dict[str, Any]:
    node_id = int(node.get("id") or 0)
    node_name = str(node.get("name") or f"node_{node_id}")
    safe_name = re.sub(r"[^\w\-.]", "_", node_name).strip("_") or f"node_{node_id}"
    file_name = f"node_{node_id}_{safe_name}.db"
    target_path = dest_dir / file_name

    async with sem:
        try:
            async with asyncio.timeout(30.0):
                api = await get_api_for_node(node)
                await api.server.get_db(str(target_path))

            if target_path.is_file() and target_path.stat().st_size > 0:
                size_bytes = target_path.stat().st_size
                logger.info(
                    "Successfully fetched 3x-ui DB from node {} ({}) — {} bytes",
                    node_id,
                    node_name,
                    size_bytes,
                )
                return {
                    "node_id": node_id,
                    "name": node_name,
                    "host": node.get("host"),
                    "file_name": file_name,
                    "size_bytes": size_bytes,
                    "ok": True,
                }
            else:
                logger.warning("Empty or missing DB file for node {} ({})", node_id, node_name)
                return {
                    "node_id": node_id,
                    "name": node_name,
                    "host": node.get("host"),
                    "ok": False,
                    "error": "empty_file",
                }
        except Exception as e:
            logger.warning("Failed to fetch 3x-ui DB from node {} ({}): {}", node_id, node_name, e)
            return {
                "node_id": node_id,
                "name": node_name,
                "host": node.get("host"),
                "ok": False,
                "error": str(e),
            }


async def _fetch_all_nodes_db(dest_dir: Path) -> list[dict[str, Any]]:
    try:
        raw_nodes = await list_nodes(enabled_only=True)
        nodes = _dedupe_nodes_by_host(raw_nodes)
    except Exception as e:
        logger.error("Failed to load xui nodes for backup: {}", e)
        return []

    if not nodes:
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    concurrency = max(1, getattr(settings, "XUI_PANEL_CONCURRENCY", 5))
    sem = asyncio.Semaphore(concurrency)
    tasks = [_fetch_single_node_db(node, dest_dir, sem) for node in nodes]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[dict[str, Any]] = []
    for r in raw_results:
        if isinstance(r, dict):
            results.append(r)
        elif isinstance(r, Exception):
            results.append({"ok": False, "error": str(r)})
    return results


async def _build_manifest(nodes_backup: dict[str, Any] | None = None) -> dict[str, Any]:
    stats = await db.get_admin_stats()
    sync_disabled = await bot_settings_db.is_sync_disabled()
    manifest: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": DB_PATH,
        "stats": stats,
        "sync_disabled": sync_disabled,
        "test_mode": await is_test_mode(),
    }
    if nodes_backup is not None:
        manifest["nodes_backup"] = nodes_backup
    return manifest


def _restore_instructions() -> str:
    return (
        "VPN Platega Bot — восстановление из бэкапа\n"
        "=====================================\n\n"
        "1. Восстановление базы данных бота (bot.db):\n"
        "   - Остановите бота (app.py и run_bot.py).\n"
        "   - Замените data/bot.db файлом bot.db из архива.\n"
        "   - Запустите бота снова.\n\n"
        "2. Восстановление баз данных нод 3x-ui (папка nodes/):\n"
        "   - В папке nodes/ содержатся дампы x-ui.db для каждой активной ноды.\n"
        "   - Для восстановления ноды остановите сервис на сервере (`x-ui stop`),"
        "\n     замените /etc/x-ui/x-ui.db файлом соответствующей ноды,"
        "\n     затем запустите сервис (`x-ui start`).\n\n"
        "В архиве также manifest.json (статистика и отчёт выгрузки нод на момент бэкапа)\n"
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
    """Собирает zip: bot.db, дампы баз нод 3x-ui, manifest.json, restore.txt, логи."""
    src_db = Path(DB_PATH)
    if not src_db.is_file():
        raise FileNotFoundError(f"Database not found: {src_db}")

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = _BACKUP_DIR / f"vpn-bot-backup_{stamp}.zip"
    tmp_db = _BACKUP_DIR / f"_tmp_bot_{stamp}.db"
    tmp_nodes_dir = _BACKUP_DIR / f"_tmp_nodes_{stamp}"

    try:
        await asyncio.to_thread(_sqlite_backup_file, src_db, tmp_db)
        node_results = await _fetch_all_nodes_db(tmp_nodes_dir)

        nodes_summary = {
            "total": len(node_results),
            "succeeded": sum(1 for r in node_results if r.get("ok")),
            "failed": sum(1 for r in node_results if not r.get("ok")),
            "details": node_results,
        }

        manifest = await _build_manifest(nodes_backup=nodes_summary)

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp_db, arcname="bot.db")
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zf.writestr("restore.txt", _restore_instructions())

            for r in node_results:
                if r.get("ok") and r.get("file_name"):
                    fpath = tmp_nodes_dir / r["file_name"]
                    if fpath.is_file():
                        zf.write(fpath, arcname=f"nodes/{r['file_name']}")

            for log_path in _collect_log_paths():
                if log_path.stat().st_size > _MAX_LOG_BYTES:
                    logger.debug("Skip large log in backup: {}", log_path)
                    continue
                zf.write(log_path, arcname=f"logs/{log_path.name}")

        _prune_local_backups(settings.BACKUP_LOCAL_RETAIN)
        logger.info(
            "Backup archive created: {} ({:.1f} KB, nodes: {}/{})",
            archive_path,
            archive_path.stat().st_size / 1024,
            nodes_summary["succeeded"],
            nodes_summary["total"],
        )
        return archive_path
    finally:
        if tmp_db.is_file():
            try:
                tmp_db.unlink()
            except OSError:
                pass
        if tmp_nodes_dir.is_dir():
            shutil.rmtree(tmp_nodes_dir, ignore_errors=True)


async def send_backup_to_admins(*, source: str = "manual") -> dict[str, Any]:
    """Создаёт архив и отправляет всем BOT_ADMINS. Возвращает сводку."""
    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Backup skipped ({}) — BOT_ADMINS empty", source)
        return {"ok": False, "reason": "no_admins", "sent": 0}

    archive = await create_backup_archive()
    size_kb = archive.stat().st_size / 1024

    manifest: dict[str, Any] = {}
    try:
        with zipfile.ZipFile(archive, "r") as zf:
            if "manifest.json" in zf.namelist():
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    except Exception as e:
        logger.warning("Failed to read manifest.json from backup archive: {}", e)

    stats = manifest.get("stats") or {}
    nodes_info = manifest.get("nodes_backup") or {}
    nodes_total = int(nodes_info.get("total", 0))
    nodes_ok = int(nodes_info.get("succeeded", 0))

    nodes_line = ""
    if nodes_total > 0:
        if nodes_ok == nodes_total:
            nodes_line = f"🌐 Ноды 3x-ui: <b>{nodes_ok}/{nodes_total}</b> сохранено\n"
        else:
            nodes_line = f"⚠️ Ноды 3x-ui: <b>{nodes_ok}/{nodes_total}</b> сохранено (ошибок: {nodes_total - nodes_ok})\n"

    created_at = str(manifest.get("created_at_utc", ""))[:19] or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    caption = (
        f"💾 <b>Бэкап бота</b> ({source})\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📅 UTC: <code>{created_at}</code>\n"
        f"📦 Размер: <b>{size_kb:.0f} KB</b>\n\n"
        f"👥 Пользователей: <b>{stats.get('users', 0)}</b>\n"
        f"✅ Платных подписок: <b>{stats.get('paid_subs', 0)}</b>\n"
        f"💰 Оплаченных заказов: <b>{stats.get('paid_orders', 0)}</b>\n"
        f"{nodes_line}\n"
        f"<i>Внутри: bot.db, manifest.json, restore.txt, базы нод, логи.</i>"
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
        logger.debug("Auto backup skipped — disabled in admin")
        return
    try:
        result = await send_backup_to_admins(source="auto")
        if result.get("ok"):
            logger.info("Scheduled backup sent to {}/{} admins", result["sent"], result["total"])
        else:
            logger.warning("Scheduled backup failed: {}", result)
    except Exception as e:
        logger.exception("Scheduled backup error: {}", e)
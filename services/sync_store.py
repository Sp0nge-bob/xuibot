"""Результаты полной синхронизации нод — общая память для run_sync.py и бота."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from config.settings import settings
from db.bot_settings import get_setting, set_setting

KEY_STATUS = "full_sync_status"
KEY_RESULT = "full_sync_result"
KEY_STARTED_AT = "full_sync_started_at"
KEY_FINISHED_AT = "full_sync_finished_at"
KEY_MANUAL_REQUEST = "full_sync_manual_request"
KEY_ERROR = "full_sync_error"


async def request_manual_sync() -> None:
    await set_setting(KEY_MANUAL_REQUEST, datetime.utcnow().isoformat())


async def peek_manual_request() -> Optional[str]:
    return await get_setting(KEY_MANUAL_REQUEST)


async def clear_manual_request() -> None:
    await set_setting(KEY_MANUAL_REQUEST, "")


async def set_sync_running() -> None:
    now = datetime.utcnow().isoformat()
    await set_setting(KEY_STATUS, "running")
    await set_setting(KEY_STARTED_AT, now)
    await set_setting(KEY_ERROR, "")


async def save_sync_success(result: dict[str, Any]) -> None:
    now = datetime.utcnow().isoformat()
    await set_setting(KEY_STATUS, "ok")
    await set_setting(KEY_RESULT, json.dumps(result, ensure_ascii=False))
    await set_setting(KEY_FINISHED_AT, now)
    await set_setting(KEY_ERROR, "")
    await clear_manual_request()


async def save_sync_error(exc: BaseException) -> None:
    now = datetime.utcnow().isoformat()
    await set_setting(KEY_STATUS, "error")
    await set_setting(KEY_FINISHED_AT, now)
    await set_setting(KEY_ERROR, f"{type(exc).__name__}: {exc}"[:500])
    await clear_manual_request()


async def get_sync_report() -> dict[str, Any]:
    status = await get_setting(KEY_STATUS) or "idle"
    finished = await get_setting(KEY_FINISHED_AT) or ""
    started = await get_setting(KEY_STARTED_AT) or ""
    error = await get_setting(KEY_ERROR) or ""
    raw = await get_setting(KEY_RESULT) or ""
    pending = await peek_manual_request() or ""
    result: dict[str, Any] = {}
    if raw:
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {}
    return {
        "status": status,
        "started_at": started,
        "finished_at": finished,
        "error": error,
        "result": result,
        "manual_pending": bool(pending.strip()),
        "manual_requested_at": pending,
    }


def format_sync_report_text(report: dict[str, Any]) -> str:
    status = report.get("status") or "idle"
    labels = {
        "idle": "ожидание",
        "running": "выполняется",
        "ok": "успешно",
        "error": "ошибка",
    }
    lines = [
        "<b>Фоновая синхронизация</b> (run_sync.py)",
        f"Статус: <b>{labels.get(status, status)}</b>",
    ]
    if report.get("manual_pending"):
        lines.append("📋 Запрос из админки в очереди")
    if report.get("started_at") and status == "running":
        lines.append(f"Старт: <code>{report['started_at'][:19]}</code>")
    if report.get("finished_at"):
        lines.append(f"Завершено: <code>{report['finished_at'][:19]}</code>")
    if status == "error" and report.get("error"):
        lines.append(f"Ошибка: <code>{report['error'][:120]}</code>")

    result = report.get("result") or {}
    p1 = result.get("phase1") or {}
    p2 = result.get("phase2") or {}
    if p1 or p2:
        lines += [
            "",
            f"Фаза 1: создано {p1.get('created', 0)}, обновлено {p1.get('updated', 0)}, "
            f"ошибок {p1.get('failed', 0)}",
            f"Фаза 2: призраков {p2.get('purged', 0)}, синхронизировано {p2.get('synced', 0)}, "
            f"ошибок {p2.get('failed', 0)}",
        ]
    lines.append("")
    lines.append(
        f"<i>Плановый интервал: {settings.FULL_SYNC_INTERVAL_HOURS} ч. "
        "Процесс: <code>python run_sync.py</code></i>"
    )
    return "\n".join(lines)
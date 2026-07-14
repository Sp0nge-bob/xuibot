"""Уведомление админу после успешного перезапуска по /reboot."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from loguru import logger

from db.bot_settings import delete_setting, get_setting, set_setting

_SETTING_KEY = "reboot_notify_pending"
_MAX_AGE_SEC = 600


async def schedule_reboot_success_notify(tg_id: int, *, detail: str = "") -> None:
    """Сохранить ожидание уведомления (переживает рестарт процесса)."""
    payload = {
        "tg_id": int(tg_id),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "detail": (detail or "").strip(),
    }
    await set_setting(_SETTING_KEY, json.dumps(payload, ensure_ascii=False))
    logger.info("Reboot notify scheduled for tg_id={}", tg_id)


async def clear_reboot_notify_pending() -> None:
    await delete_setting(_SETTING_KEY)


async def _load_pending() -> dict[str, Any] | None:
    raw = await get_setting(_SETTING_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        tg_id = int(data.get("tg_id") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Invalid reboot_notify payload: {}", raw[:200])
        await clear_reboot_notify_pending()
        return None
    if tg_id <= 0:
        await clear_reboot_notify_pending()
        return None
    return data


def _elapsed_sec(requested_at: str) -> int | None:
    try:
        started = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - started.astimezone(timezone.utc)
        return max(0, int(delta.total_seconds()))
    except (TypeError, ValueError):
        return None


async def send_pending_reboot_notification(bot: Bot) -> None:
    """После полного старта бота — сообщить админу об успешном /reboot."""
    data = await _load_pending()
    if not data:
        return

    tg_id = int(data["tg_id"])
    elapsed = _elapsed_sec(str(data.get("requested_at") or ""))
    if elapsed is not None and elapsed > _MAX_AGE_SEC:
        logger.warning("Reboot notify expired ({}s) — skip", elapsed)
        await clear_reboot_notify_pending()
        return

    await clear_reboot_notify_pending()
    elapsed_line = (
        f"⏱ Запуск за <b>{elapsed}</b> с после /reboot\n"
        if elapsed is not None
        else ""
    )
    detail = (data.get("detail") or "").strip()
    detail_line = f"<i>{detail}</i>\n" if detail else ""

    text = (
        "✅ <b>Перезапуск завершён</b>\n"
        "vpn-bot-telegram · vpn-bot-web — работают\n\n"
        f"{elapsed_line}"
        f"{detail_line}"
        f"PID: <code>{os.getpid()}</code>"
    )

    try:
        await bot.send_message(tg_id, text)
        logger.info("Reboot success notify sent to tg_id={}", tg_id)
    except Exception as e:
        logger.error("Reboot notify failed for tg_id={}: {}", tg_id, e)
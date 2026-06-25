"""Напоминания пользователям об истечении платной подписки."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from services.subscription_labels import subscription_display_name
from ui.theme import days_left, format_date, screen


def expiry_reminder_text(subs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for sub in subs:
        name = subscription_display_name(sub)
        end = format_date(sub["end_date"])
        left = days_left(sub["end_date"])
        day_word = "день" if left == 1 else "дня" if 2 <= left <= 4 else "дней"
        lines.append(
            f"📱 <b>{name}</b> — до <b>{end}</b> "
            f"(осталось <b>{left}</b> {day_word})"
        )
    body = "\n".join(lines)
    footer = (
        "Продлите заранее в разделе «Покупка», чтобы VPN не отключился."
        if len(subs) == 1
        else "Продлите подписки заранее в разделе «Покупка», чтобы VPN не отключился."
    )
    return screen("⏰ <b>Подписка скоро закончится</b>", body, footer=footer)


async def send_expiry_reminders() -> dict[str, int]:
    """Отправляет напоминания; возвращает счётчики sent/failed/skipped."""
    if not settings.EXPIRY_REMINDER_ENABLED:
        return {"sent": 0, "failed": 0, "skipped": 0, "subs": 0}

    subs = await db.get_subscriptions_needing_expiry_reminder(
        days_before=settings.EXPIRY_REMINDER_DAYS,
        min_hours_since_reminder=settings.EXPIRY_REMINDER_INTERVAL_HOURS,
    )
    if not subs:
        return {"sent": 0, "failed": 0, "skipped": 0, "subs": 0}

    by_tg: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sub in subs:
        by_tg[int(sub["tg_id"])].append(sub)

    from bot.keyboards import expiry_reminder_kb
    from bot.sender import send_message

    sent = failed = 0
    for tg_id, user_subs in by_tg.items():
        sub_ids = [int(s["id"]) for s in user_subs]
        try:
            await send_message(
                tg_id,
                expiry_reminder_text(user_subs),
                reply_markup=expiry_reminder_kb(),
            )
            await db.mark_expiry_reminders_sent(sub_ids)
            sent += 1
            logger.info(
                "Expiry reminder sent to tg_id={} ({} subs)",
                tg_id,
                len(user_subs),
            )
        except Exception as e:
            failed += 1
            logger.error(
                "Expiry reminder failed for tg_id={} (subs {}): {}",
                tg_id,
                sub_ids,
                e,
            )

    return {"sent": sent, "failed": failed, "skipped": 0, "subs": len(subs)}
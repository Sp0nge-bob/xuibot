"""Массовое продление: БД бота + clients/bulkAdjust addDays на ★ Primary."""
from __future__ import annotations

from typing import Any

from loguru import logger

from db import database as db
from services.admin_extend import admin_bulk_extend_notify_text
from services.xui import bulk_adjust_client_days, is_bot_client_email


async def bulk_add_days_to_all_active(days: int, *, admin_tg_id: int | None = None) -> dict[str, Any]:
    days = int(days)
    if days <= 0:
        raise ValueError("Число дней должно быть больше 0")
    if days > 3650:
        raise ValueError("Слишком большой срок (макс. 3650 дней)")

    subs = await db.get_all_active_subscriptions()
    emails: list[str] = []
    seen: set[str] = set()
    for sub in subs:
        email = str(sub.get("client_email") or "").strip()
        if not email or email in seen or not is_bot_client_email(email):
            continue
        seen.add(email)
        emails.append(email)

    panel: dict[str, Any] = {"adjusted": 0, "skipped": [], "emails": len(emails)}
    panel_error: str | None = None
    if emails:
        try:
            panel = await bulk_adjust_client_days(emails, days)
        except Exception as e:
            logger.exception("bulkAdjust +{}d failed: {}", days, e)
            raise ValueError(f"Панель не приняла bulkAdjust: {e}") from e

    db_updated = 0
    db_failed = 0
    notify_ids: list[int] = []
    notify_seen: set[int] = set()
    for sub in subs:
        try:
            await db.extend_subscription_record(int(sub["id"]), days)
            db_updated += 1
            tg_id = int(sub["tg_id"])
            if tg_id not in notify_seen:
                notify_seen.add(tg_id)
                notify_ids.append(tg_id)
        except Exception as e:
            db_failed += 1
            logger.error("Bulk extend DB sub #{}: {}", sub.get("id"), e)

    logger.success(
        "Bulk extend +{}d db={} panel={} skipped={} admin_tg={}",
        days,
        db_updated,
        panel.get("adjusted"),
        len(panel.get("skipped") or []),
        admin_tg_id,
    )
    return {
        "days": days,
        "db_updated": db_updated,
        "db_failed": db_failed,
        "panel_adjusted": int(panel.get("adjusted") or 0),
        "panel_skipped": len(panel.get("skipped") or []),
        "panel_error": panel_error,
        "notify_ids": notify_ids,
        "notify_text": admin_bulk_extend_notify_text(days=days),
        "sub_count": len(subs),
    }

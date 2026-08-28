"""Ручное продление подписки администратором (БД + Primary + уведомление клиенту)."""
from __future__ import annotations

from loguru import logger

from db import database as db
from services.xui import extend_client, get_unified_panel_client
from utils.utc import utc_iso_to_ms


def admin_extend_notify_text(*, days: int, new_end_date: str) -> str:
    end_s = (new_end_date or "")[:10] or "—"
    n = int(days)
    return (
        f"Ваша подписка была продлена администратором на <b>{n}</b> "
        f"{'день' if n % 10 == 1 and n % 100 != 11 else 'дня' if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 'дней'}.\n"
        f"Новый срок: до <b>{end_s}</b>."
    )


async def admin_extend_subscription(
    subscription_id: int,
    days: int,
    *,
    admin_tg_id: int | None = None,
) -> dict:
    """
    Продлить активную подписку на days дней.
    Возвращает {subscription, new_end_iso, days}.
    """
    days = int(days)
    if days <= 0:
        raise ValueError("Число дней должно быть больше 0")
    if days > 3650:
        raise ValueError("Слишком большой срок (макс. 3650 дней)")

    sub = await db.get_subscription_by_id(subscription_id)
    if not sub or not sub.get("is_active"):
        raise ValueError("Подписка не найдена или неактивна")

    new_end_iso = await db.extend_subscription_record(subscription_id, days)
    new_expiry_ms = utc_iso_to_ms(new_end_iso)
    email = sub["client_email"]
    panel_client = await get_unified_panel_client(email)
    if panel_client:
        await extend_client(
            email,
            days,
            target_expiry_ms=new_expiry_ms,
        )
    else:
        logger.warning(
            "Admin extend #{}: клиент {} нет на панели — обновлена только БД",
            subscription_id,
            email,
        )

    logger.success(
        "Admin extend sub #{} +{}d → {} (admin_tg={})",
        subscription_id,
        days,
        new_end_iso[:10],
        admin_tg_id,
    )
    refreshed = await db.get_subscription_by_id(subscription_id)
    return {
        "subscription": refreshed or sub,
        "new_end_iso": new_end_iso,
        "days": days,
    }

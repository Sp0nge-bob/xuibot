"""Ротация subId ссылки подписки: панель Primary + БД, uuid/срок не трогаем."""
from __future__ import annotations

import secrets

from loguru import logger

from db import database as db
from services.xui import build_sub_link, rotate_client_sub_id


def _fresh_sub_id(old: str) -> str:
    old = (old or "").strip()
    for _ in range(8):
        token = secrets.token_urlsafe(12)[:16]
        if token and token != old:
            return token
    raise ValueError("Не удалось сгенерировать новый subId")


def admin_rotate_link_notify_text(*, link: str) -> str:
    from html import escape

    safe = escape(link)
    return (
        "Ваша ссылка на подписку была перегенерирована.\n\n"
        "Новая ссылка:\n"
        f"<code>{safe}</code>\n\n"
        "Старая ссылка, которую вы использовали ранее, теперь неактивна."
    )


async def admin_rotate_subscription_link(
    subscription_id: int,
    *,
    admin_tg_id: int | None = None,
) -> dict:
    """
    Новый subId на ★ Primary и в БД. Остальные поля клиента не меняются.
    Возвращает {subscription, old_sub_id, new_sub_id, link}.
    """
    sub = await db.get_subscription_by_id(subscription_id)
    if not sub or not sub.get("is_active"):
        raise ValueError("Подписка не найдена или неактивна")

    email = str(sub.get("client_email") or "").strip()
    if not email:
        raise ValueError("У подписки нет email клиента")

    old_sub_id = str(sub.get("sub_id") or "").strip()
    new_sub_id = _fresh_sub_id(old_sub_id)

    await rotate_client_sub_id(email, new_sub_id)
    await db.update_subscription_sub_id(subscription_id, new_sub_id)
    link = await build_sub_link(new_sub_id)

    logger.success(
        "Admin rotate sub #{} {} → {} (admin_tg={})",
        subscription_id,
        old_sub_id or "—",
        new_sub_id,
        admin_tg_id,
    )
    refreshed = await db.get_subscription_by_id(subscription_id)
    return {
        "subscription": refreshed or sub,
        "old_sub_id": old_sub_id,
        "new_sub_id": new_sub_id,
        "link": link,
    }

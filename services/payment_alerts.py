"""Уведомления админам об успешных оплатах."""
from __future__ import annotations

import html
from typing import Any, Dict, Optional

from loguru import logger

from config.payments import get_payment_method_by_key
from config.settings import settings
from db import database as db
from db.bot_settings import is_payment_admin_notify_enabled
from ui.theme import money


def _user_display(
    *,
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> str:
    if username:
        name = html.escape(first_name or username)
        return f"@{html.escape(username)} ({name})"
    if first_name:
        return html.escape(first_name)
    return f"<code>{tg_id}</code>"


def format_payment_admin_notify_text(order: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> str:
    raw_tg_id = order.get("tg_id")
    tg_id = int(raw_tg_id) if raw_tg_id and int(raw_tg_id) > 0 else 0
    username = (user or {}).get("username")
    first_name = (user or {}).get("first_name")

    plan_name = html.escape(str(order.get("plan_name") or "—"))
    amount = int(order.get("amount") or order.get("final_amount") or 0)
    order_id = order.get("id") or "—"
    tx_id = html.escape(str(order.get("platega_tx_id") or "—"))
    order_type = str(order.get("order_type") or "new").lower()
    if order_type == "extend":
        sub_name = str(order.get("sub_display_name") or "").strip()
        sub_id = order.get("subscription_id")
        if sub_name and not sub_name.startswith("Sub #"):
            action = f"Продление (<b>{html.escape(sub_name)}</b>)"
        elif sub_id:
            action = f"Продление (<b>Подписка #{sub_id}</b>)"
        else:
            action = "Продление"
    else:
        action = "Новая подписка"

    source = str(order.get("source") or "bot").lower()
    source_label = "🌐 Сайт" if source in ("web", "website") else "🤖 Бот"

    lines = [
        "💰 <b>Новая оплата</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"📱 Источник: <b>{source_label}</b>",
    ]

    if tg_id > 0:
        lines.append(f"👤 Клиент: {_user_display(tg_id=tg_id, username=username, first_name=first_name)}")
        lines.append(f"🆔 TG ID: <code>{tg_id}</code>")
    else:
        lines.append("👤 Клиент: <i>Веб-пользователь</i>")

    cust_email = str(order.get("customer_email") or "").strip()
    if cust_email:
        lines.append(f"✉️ Email: <code>{html.escape(cust_email)}</code>")

    lines.extend([
        "",
        f"📦 Тариф: <b>{plan_name}</b>",
        f"💵 Сумма: {money(amount)}",
        f"🔄 Тип: <b>{action}</b>",
        "",
        f"🧾 Заказ: <code>#{order_id}</code>",
        f"🆔 TX Platega: <code>{tx_id}</code>",
    ])

    method_key = (order.get("payment_method") or "").strip()
    if method_key:
        method = get_payment_method_by_key(method_key)
        if method:
            lines.append(f"🏦 Способ: {method['emoji']} <b>{html.escape(method['name'])}</b>")

    promo = (order.get("promo_code") or "").strip()
    discount = int(order.get("discount_amount") or 0)
    if promo:
        lines.append(f"🎟 Промокод: <code>{html.escape(promo)}</code>")
    elif discount > 0:
        lines.append(f"👥 Реферальная скидка: <b>−{discount} ₽</b>")

    if str(order.get("platega_tx_id") or "").startswith("test-"):
        lines += ["", "⚠️ <i>Тестовый режим — оплата симулирована</i>"]

    return "\n".join(lines)


async def notify_admins_payment_success(order: Dict[str, Any]) -> int:
    """Отправляет всем BOT_ADMINS уведомление об успешной оплате. Возвращает число доставок."""
    if not await is_payment_admin_notify_enabled():
        return 0

    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Payment admin notify skipped — BOT_ADMINS empty")
        return 0

    raw_tg_id = order.get("tg_id")
    user = await db.get_user(int(raw_tg_id)) if raw_tg_id and int(raw_tg_id) > 0 else None
    text = format_payment_admin_notify_text(order, user)

    from bot.sender import send_message

    sent = 0
    for admin_id in admin_ids:
        try:
            await send_message(admin_id, text)
            sent += 1
        except Exception as e:
            logger.error("Payment admin notify failed for admin {}: {}", admin_id, e)
    if sent:
        logger.info(
            "Payment admin notify sent to {} admin(s), order #{} tg={}",
            sent,
            order.get("id"),
            order.get("tg_id"),
        )
    return sent
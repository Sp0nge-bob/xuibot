"""Обогащение заказа данными реферера для админ-чеков."""
from __future__ import annotations

from typing import Any

from db import database as db
from db import referrals as ref_db


async def enrich_order_with_referrer(order: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Если скидка реферальная (есть discount, нет promo_code) —
    добавить referrer_tg_id / username / first_name.
    """
    if not order:
        return order
    if (order.get("promo_code") or "").strip():
        return order
    if int(order.get("discount_amount") or 0) <= 0:
        return order
    if order.get("referrer_tg_id") is not None:
        return order

    try:
        buyer_tg = int(order["tg_id"])
    except (KeyError, TypeError, ValueError):
        return order

    referrer_id = await ref_db.get_referrer_tg_id(buyer_tg)
    if not referrer_id:
        # fallback: колонка users.referred_by_tg_id
        flags = await ref_db.get_user_referral_flags(buyer_tg)
        raw = flags.get("referred_by_tg_id")
        if raw:
            try:
                referrer_id = int(raw)
            except (TypeError, ValueError):
                referrer_id = None
    if not referrer_id:
        return order

    user = await db.get_user(int(referrer_id))
    return {
        **order,
        "referrer_tg_id": int(referrer_id),
        "referrer_username": (user or {}).get("username"),
        "referrer_first_name": (user or {}).get("first_name"),
    }

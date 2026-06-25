"""Проверка доступности возврата по подписке."""
from __future__ import annotations

from datetime import datetime, timedelta

REFUND_PROMO_TAIL_ALERT = (
    "Сейчас активны дни по промокоду — возврат недоступен"
)
REFUND_GRANT_SUB_ALERT = (
    "Подписка получена по промокоду — возврат недоступен"
)


def _parse_dt(iso: str) -> datetime:
    return datetime.fromisoformat(str(iso).replace("Z", ""))


def subscription_paid_end_date(sub: dict) -> datetime | None:
    """Конец оплаченного периода без grant-дней промокода."""
    bonus = int(sub.get("grant_bonus_days") or 0)
    if bonus <= 0:
        return None
    end = _parse_dt(sub["end_date"])
    return end - timedelta(days=bonus)


def is_on_promo_only_period(sub: dict, *, now: datetime | None = None) -> bool:
    """
    True, если оплаченный срок истёк, а подписка ещё активна за счёт grant-промокода.
    """
    paid_end = subscription_paid_end_date(sub)
    if paid_end is None:
        return False
    now = now or datetime.utcnow()
    if not sub.get("is_active"):
        return False
    try:
        sub_end = _parse_dt(sub["end_date"])
    except (TypeError, ValueError):
        return False
    return paid_end < now <= sub_end


def is_grant_only_subscription(sub: dict, *, has_paid_orders: bool) -> bool:
    """Подписка выдана grant-промокодом, без оплат."""
    if has_paid_orders:
        return False
    return sub.get("order_id") is None


def refund_denied_alert(sub: dict, *, has_paid_orders: bool) -> str | None:
    """Текст alert, если возврат запрещён; иначе None."""
    if is_on_promo_only_period(sub):
        return REFUND_PROMO_TAIL_ALERT
    if is_grant_only_subscription(sub, has_paid_orders=has_paid_orders):
        return REFUND_GRANT_SUB_ALERT
    return None
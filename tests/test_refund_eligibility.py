"""Возврат нельзя на хвосте grant-промо и на чисто grant-подписке."""
from __future__ import annotations

from datetime import datetime

from services.refund_eligibility import (
    REFUND_GRANT_SUB_ALERT,
    REFUND_PROMO_TAIL_ALERT,
    is_grant_only_subscription,
    is_on_promo_only_period,
    refund_denied_alert,
    subscription_paid_end_date,
)

NOW_MAY_8 = datetime(2026, 5, 8, 12, 0, 0)


def _sub(**overrides) -> dict:
    sub = {
        "is_active": 1,
        "end_date": "2026-05-11T00:00:00",
        "grant_bonus_days": 3,
        "order_id": 10,
    }
    sub.update(overrides)
    return sub


def test_paid_end_none_without_bonus():
    assert subscription_paid_end_date(_sub(grant_bonus_days=0)) is None
    assert is_on_promo_only_period(_sub(grant_bonus_days=0), now=NOW_MAY_8) is False


def test_still_in_paid_period():
    assert is_on_promo_only_period(_sub(), now=datetime(2026, 5, 7, 12, 0, 0)) is False


def test_promo_tail():
    assert is_on_promo_only_period(_sub(), now=datetime(2026, 5, 9, 12, 0, 0)) is True


def test_already_expired():
    assert is_on_promo_only_period(_sub(), now=datetime(2026, 5, 12, 0, 0, 0)) is False


def test_inactive():
    assert is_on_promo_only_period(_sub(is_active=0), now=datetime(2026, 5, 9, 12, 0, 0)) is False


def test_bad_end_date_no_raise():
    assert is_on_promo_only_period(_sub(end_date="nope"), now=NOW_MAY_8) is False


def test_grant_only_no_paid_orders():
    assert is_grant_only_subscription(_sub(order_id=None), has_paid_orders=False) is True


def test_grant_but_had_payments():
    assert is_grant_only_subscription(_sub(order_id=None), has_paid_orders=True) is False


def test_alert_promo_tail():
    text = refund_denied_alert(
        _sub(),
        has_paid_orders=True,
        now=datetime(2026, 5, 9, 12, 0, 0),
    )
    assert text == REFUND_PROMO_TAIL_ALERT


def test_alert_grant_only():
    # Без grant-хвоста: иначе сработает promo-tail раньше grant-only.
    text = refund_denied_alert(
        _sub(order_id=None, grant_bonus_days=0),
        has_paid_orders=False,
        now=NOW_MAY_8,
    )
    assert text == REFUND_GRANT_SUB_ALERT

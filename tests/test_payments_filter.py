"""Фильтр методов оплаты и поиск тарифа по id."""
from __future__ import annotations

from config.payments import filter_payment_methods
from config.plans import get_plan


def _methods():
    return [
        {"key": "sbp", "name": "СБП", "emoji": "🏦", "platega_id": 2},
        {"key": "crypto", "name": "Крипто", "emoji": "₿", "platega_id": 13},
        {"key": "card", "name": "Карта", "emoji": "💳", "platega_id": 11},
    ]


def test_filter_enabled_only():
    enabled = {"sbp": True, "crypto": True, "card": False}
    out = filter_payment_methods(_methods(), enabled)
    assert [m["key"] for m in out] == ["sbp", "crypto"]


def test_filter_unknown_key_dropped():
    out = filter_payment_methods(_methods(), {"sbp": True, "unknown": True})
    assert [m["key"] for m in out] == ["sbp"]


def test_get_plan_known():
    plan = get_plan("1m")
    assert plan is not None
    assert plan["id"] == "1m"


def test_get_plan_unknown():
    assert get_plan("nope") is None

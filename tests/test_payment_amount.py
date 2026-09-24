"""Комиссия Platega в callback: до 25% сверху заказа — не mismatch."""
from __future__ import annotations

from services.payment_processor import _callback_amount_acceptable


def test_amount_exact_match():
    assert _callback_amount_acceptable(300, 300) is True


def test_amount_commission_kopecks():
    assert _callback_amount_acceptable(300, 300.13) is True


def test_amount_commission_ceiling_25_percent():
    assert _callback_amount_acceptable(300, 375) is True


def test_amount_above_commission_ceiling():
    assert _callback_amount_acceptable(300, 376) is False


def test_amount_below_order():
    assert _callback_amount_acceptable(300, 299) is False


def test_amount_missing_callback():
    assert _callback_amount_acceptable(300, None) is True


def test_amount_garbage():
    assert _callback_amount_acceptable(300, "abc") is False


def test_amount_numeric_string():
    assert _callback_amount_acceptable(300, "300") is True

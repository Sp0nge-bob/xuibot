"""Скидки и quote из сохранённого заказа."""
from __future__ import annotations

from services.pricing import _promo_plan_allowed, calc_discount, quote_from_order


def test_calc_discount_percent():
    assert calc_discount(300, "percent", 20) == 60


def test_calc_discount_percent_100():
    assert calc_discount(300, "percent", 100) == 300


def test_calc_discount_fixed_below_price():
    assert calc_discount(300, "fixed", 50) == 50


def test_calc_discount_fixed_above_price():
    assert calc_discount(300, "fixed", 999) == 300


def test_quote_from_order_explicit_discount(plan_1m):
    quote = quote_from_order(
        {"amount": 240, "original_amount": 300, "discount_amount": 60, "promo_code": "SALE"},
        plan_1m,
    )
    assert quote.final_price == 240
    assert quote.base_price == 300
    assert quote.discount_amount == 60
    assert quote.has_discount is True


def test_quote_from_order_discount_from_difference(plan_1m):
    quote = quote_from_order(
        {"amount": 240, "original_amount": 300},
        plan_1m,
    )
    assert quote.discount_amount == 60


def test_quote_from_order_source_promo(plan_1m):
    quote = quote_from_order(
        {"amount": 240, "original_amount": 300, "promo_code": "SALE"},
        plan_1m,
    )
    assert quote.discount_source == "promo"


def test_quote_from_order_source_referral(plan_1m):
    quote = quote_from_order(
        {"amount": 240, "original_amount": 300, "discount_amount": 60},
        plan_1m,
    )
    assert quote.discount_source == "referral"
    assert quote.promo_code is None


def test_quote_from_order_no_discount(plan_1m):
    quote = quote_from_order({"amount": 300, "original_amount": 300}, plan_1m)
    assert quote.has_discount is False
    assert quote.discount_source is None


def test_promo_plan_allowed_empty_means_all():
    assert _promo_plan_allowed({"plan_ids": ""}, "12m") is True
    assert _promo_plan_allowed({"plan_ids": "   "}, "1m") is True


def test_promo_plan_allowed_whitelist():
    promo = {"plan_ids": "1m, 3m"}
    assert _promo_plan_allowed(promo, "1m") is True
    assert _promo_plan_allowed(promo, "6m") is False

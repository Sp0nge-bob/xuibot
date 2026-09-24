"""Парсинг ref-ссылок, тиры скидки, welcome vs tier."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from db.referrals import tier_discount_percent
from services.referral import build_referral_link, calc_referral_discount_amount, parse_referral_start_arg


def test_parse_referral_start_arg_prefix():
    assert parse_referral_start_arg("ref_123") == 123


def test_parse_referral_start_arg_bare_id():
    assert parse_referral_start_arg("123") == 123


@pytest.mark.parametrize("raw", [None, "", "ref_abc", "ref_0", "ref_-1"])
def test_parse_referral_start_arg_invalid(raw):
    assert parse_referral_start_arg(raw) is None


def test_build_referral_link():
    assert build_referral_link("MyBot", 5) == "https://t.me/MyBot?start=ref_5"


def test_build_referral_link_strips_at():
    assert build_referral_link("@MyBot", 5) == "https://t.me/MyBot?start=ref_5"


def test_tier_discount_percent_zero():
    assert tier_discount_percent(0) == 0


def test_tier_discount_percent_one_friend():
    assert tier_discount_percent(1) == 10


def test_tier_discount_percent_two_friends():
    assert tier_discount_percent(2) == 15


def test_tier_discount_percent_cap():
    assert tier_discount_percent(5) == 30
    assert tier_discount_percent(100) == 30


async def test_welcome_discount_first_payment(monkeypatch):
    from services import referral as referral_mod

    monkeypatch.setattr(
        referral_mod.ref_db,
        "get_user_referral_flags",
        AsyncMock(return_value={"referral_welcome_used": False, "referred_by_tg_id": 1}),
    )
    monkeypatch.setattr(referral_mod.ref_db, "count_paid_orders", AsyncMock(return_value=0))
    monkeypatch.setattr(
        referral_mod.ref_db, "get_referrer_tier_discount_percent", AsyncMock(return_value=0),
    )
    assert await calc_referral_discount_amount(99, 300) == 60


async def test_welcome_already_used(monkeypatch):
    from services import referral as referral_mod

    monkeypatch.setattr(
        referral_mod.ref_db,
        "get_user_referral_flags",
        AsyncMock(return_value={"referral_welcome_used": True, "referred_by_tg_id": 1}),
    )
    monkeypatch.setattr(referral_mod.ref_db, "count_paid_orders", AsyncMock(return_value=0))
    monkeypatch.setattr(
        referral_mod.ref_db, "get_referrer_tier_discount_percent", AsyncMock(return_value=0),
    )
    assert await calc_referral_discount_amount(99, 300) == 0


async def test_welcome_vs_tier_takes_max(monkeypatch):
    from services import referral as referral_mod

    monkeypatch.setattr(
        referral_mod.ref_db,
        "get_user_referral_flags",
        AsyncMock(return_value={"referral_welcome_used": False, "referred_by_tg_id": 1}),
    )
    monkeypatch.setattr(referral_mod.ref_db, "count_paid_orders", AsyncMock(return_value=0))
    monkeypatch.setattr(
        referral_mod.ref_db, "get_referrer_tier_discount_percent", AsyncMock(return_value=30),
    )
    assert await calc_referral_discount_amount(99, 300) == 90


async def test_referral_discount_zero_price(monkeypatch):
    assert await calc_referral_discount_amount(99, 0) == 0

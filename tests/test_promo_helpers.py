"""Нормализация промокода и validate без SQLite."""
from __future__ import annotations

from unittest.mock import AsyncMock

from db.promo_codes import _normalize_code, grant_plan_id, is_grant_promo
from services.pricing import _validate_promo_common, validate_promo


def test_normalize_code():
    assert _normalize_code("  sale ") == "SALE"


def test_is_grant_promo():
    assert is_grant_promo({"promo_type": "grant"}) is True
    assert is_grant_promo({}) is False
    assert is_grant_promo({"promo_type": "discount"}) is False


def test_grant_plan_id_first_of_list():
    assert grant_plan_id({"promo_type": "grant", "plan_ids": "3m,6m"}) == "3m"
    assert grant_plan_id({"promo_type": "grant", "plan_ids": ""}) is None


def test_grant_plan_id_on_discount_is_none():
    assert grant_plan_id({"promo_type": "discount", "plan_ids": "1m"}) is None


def _discount_promo(**overrides) -> dict:
    promo = {
        "id": 1,
        "code": "SALE",
        "promo_type": "discount",
        "discount_type": "percent",
        "discount_value": 20,
        "is_active": 1,
        "plan_ids": "",
        "used_count": 0,
        "max_uses": None,
        "per_user_limit": 0,
        "valid_until": None,
    }
    promo.update(overrides)
    return promo


async def test_validate_promo_not_found(monkeypatch):
    from services import pricing as pricing_mod

    monkeypatch.setattr(pricing_mod.promo_db, "get_promo_by_code", AsyncMock(return_value=None))
    promo, err = await validate_promo("NOPE", plan_id="1m", tg_id=1)
    assert promo is None
    assert err == "Промокод не найден"


async def test_validate_promo_grant_as_discount(monkeypatch):
    from services import pricing as pricing_mod

    monkeypatch.setattr(
        pricing_mod.promo_db,
        "get_promo_by_code",
        AsyncMock(return_value=_discount_promo(promo_type="grant", plan_ids="1m")),
    )
    promo, err = await validate_promo("FREE", plan_id="1m", tg_id=1)
    assert promo is None
    assert "бесплатно" in (err or "")
    assert "Покупка" in (err or "")


async def test_validate_promo_wrong_plan(monkeypatch):
    from services import pricing as pricing_mod

    monkeypatch.setattr(
        pricing_mod.promo_db,
        "get_promo_by_code",
        AsyncMock(return_value=_discount_promo(plan_ids="1m")),
    )
    promo, err = await validate_promo("SALE", plan_id="3m", tg_id=1)
    assert promo is None
    assert err == "Промокод не действует на этот тариф"


async def test_validate_promo_disabled():
    err = await _validate_promo_common(_discount_promo(is_active=0), tg_id=1)
    assert err == "Промокод отключён"


async def test_validate_promo_expired():
    err = await _validate_promo_common(
        _discount_promo(valid_until="2020-01-01T00:00:00"),
        tg_id=1,
    )
    assert err == "Срок действия промокода истёк"


async def test_validate_promo_max_uses():
    err = await _validate_promo_common(
        _discount_promo(max_uses=5, used_count=5),
        tg_id=1,
    )
    assert err == "Промокод исчерпан"


async def test_validate_promo_per_user_once(monkeypatch):
    from db import promo_codes as promo_db

    monkeypatch.setattr(promo_db, "count_user_promo_uses", AsyncMock(return_value=1))
    err = await _validate_promo_common(_discount_promo(per_user_limit=1), tg_id=1)
    assert err == "Вы уже использовали этот промокод"


async def test_validate_promo_per_user_n(monkeypatch):
    from db import promo_codes as promo_db

    monkeypatch.setattr(promo_db, "count_user_promo_uses", AsyncMock(return_value=3))
    err = await _validate_promo_common(_discount_promo(per_user_limit=3), tg_id=1)
    assert err == "Лимит промокода для вас исчерпан (3 раз)"

"""Юнит-тесты: без прод-.env и без data/bot.db."""
from __future__ import annotations

import os
from datetime import datetime

# До любых импортов проекта: не читать .env, обязательные поля — заглушки.
os.environ["PYTEST_RUNNING"] = "1"
os.environ.setdefault("BOT_TOKEN", "0:pytest")
os.environ.setdefault("PLATEGA_MERCHANT_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("PLATEGA_SECRET", "pytest-secret")
os.environ.setdefault("XUI_HOST", "https://example.test/")

import pytest

FIXED_NOW = datetime(2026, 5, 8, 12, 0, 0)

PLAN_1M = {
    "id": "1m",
    "name": "1 месяц",
    "days": 30,
    "price": 300,
    "traffic_gb": 0,
}


@pytest.fixture
def fixed_now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def plan_1m() -> dict:
    return dict(PLAN_1M)

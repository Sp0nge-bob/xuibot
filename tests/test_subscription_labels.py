"""Имя подписки в кнопках: лимит 32, без мусора."""
from __future__ import annotations

from services.subscription_labels import (
    normalize_display_name,
    subscription_display_name,
    subscription_short_label,
)


def test_display_name_custom():
    assert subscription_display_name({"display_name": "Дом"}) == "Дом"


def test_display_name_trial_default():
    assert subscription_display_name({"client_email": "tgfree1", "display_name": ""}) == "Пробная"


def test_display_name_paid_default():
    assert subscription_display_name({"client_email": "tg1", "display_name": ""}) == "Платная"


def test_short_label_prefixes():
    assert subscription_short_label({"client_email": "tgfree1"}).startswith("🎁")
    assert subscription_short_label({"client_email": "tg1"}).startswith("📱")


def test_normalize_collapses_spaces():
    assert normalize_display_name("  Дом   VPN  ") == "Дом VPN"


def test_normalize_rejects_empty_long_emoji():
    assert normalize_display_name("") is None
    assert normalize_display_name("x" * 33) is None
    assert normalize_display_name("🔥огонь") is None

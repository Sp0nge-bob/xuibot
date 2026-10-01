"""Unit tests for INCY crypt1 encryption, redirect URLs, and UI keyboards."""
from __future__ import annotations

import pytest

from bot.keyboards import (
    faq_activation_choice_kb,
    fulfillment_success_kb,
    sub_link_client_picker_kb,
    sub_link_result_kb,
    subscription_manage_kb,
)
from bot.messages import subscription_manage_text
from services.fulfillment_text import (
    happ_setup_text,
    incy_setup_text,
    sub_link_needs_separate_message,
)
from services.incy_crypto import (
    build_incy_redirect_url,
    decrypt_incy_crypt1,
    encrypt_incy_crypt1,
)


def test_encrypt_decrypt_incy_crypt1_default_name():
    plain_url = "https://sub.example.com/sub/testkey123"
    encrypted = encrypt_incy_crypt1(plain_url)
    assert encrypted.startswith("incy://crypt1/")

    # Deterministic: calling twice yields identical link
    assert encrypt_incy_crypt1(plain_url) == encrypted

    payload = decrypt_incy_crypt1(encrypted)
    assert payload["url"] == plain_url
    assert payload["name"].endswith("VPN")


def test_encrypt_decrypt_incy_crypt1_custom_name():
    plain_url = "https://sub.example.com/sub/testkey456"
    encrypted = encrypt_incy_crypt1(plain_url, name="iPhone 15")
    payload = decrypt_incy_crypt1(encrypted)
    assert payload["url"] == plain_url
    assert payload["name"] == "iPhone 15 VPN"

    # Idempotent " VPN" suffix
    encrypted2 = encrypt_incy_crypt1(plain_url, name="Home VPN")
    payload2 = decrypt_incy_crypt1(encrypted2)
    assert payload2["name"] == "Home VPN"


def test_encrypt_incy_crypt1_empty_and_invalid_decrypt():
    assert encrypt_incy_crypt1("   ") == ""
    with pytest.raises(ValueError):
        decrypt_incy_crypt1("https://not-an-incy-link.example.com")


def test_build_incy_redirect_url(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "WEBSITE_PUBLIC_URL", "https://sub.example.com")
    assert build_incy_redirect_url("abc123xyz") == "https://sub.example.com/incy/abc123xyz"


def test_sub_link_needs_separate_message_supports_incy():
    assert sub_link_needs_separate_message("incy://crypt1/abcdef") is True
    assert sub_link_needs_separate_message("happ://crypt3/abcdef") is True
    assert sub_link_needs_separate_message("https://sub.example.com/sub/abc") is False


def test_subscription_manage_kb_places_happ_and_incy_side_by_side():
    kb = subscription_manage_kb(
        42,
        happ_url="https://sub.example.com/happ/k1",
        incy_url="https://sub.example.com/incy/k1",
    )
    first_row = kb.inline_keyboard[0]
    assert len(first_row) == 2
    assert first_row[0].text == "📱 Добавить в Happ"
    assert first_row[0].url == "https://sub.example.com/happ/k1"
    assert first_row[1].text == "🛡 Добавить в INCY"
    assert first_row[1].url == "https://sub.example.com/incy/k1"


def test_fulfillment_success_kb_structure():
    kb = fulfillment_success_kb(
        happ_url="https://sub.example.com/happ/k1",
        incy_url="https://sub.example.com/incy/k1",
        sub_id=77,
    )
    rows = kb.inline_keyboard
    # Row 0: Happ + INCY
    assert len(rows[0]) == 2
    assert rows[0][0].text == "📱 Добавить в Happ"
    assert rows[0][1].text == "🛡 Добавить в INCY"
    # Row 1: Ссылка и QR
    assert rows[1][0].text == "🔗 Ссылка и QR"
    assert rows[1][0].callback_data == "sub_link:77"
    # Row 2: Как подключить подписку
    assert rows[2][0].callback_data == "faq:builtin:activation"


def test_sub_link_client_picker_and_result_kb():
    picker = sub_link_client_picker_kb(55)
    assert picker.inline_keyboard[0][0].callback_data == "sub_link:55:happ"
    assert picker.inline_keyboard[0][1].callback_data == "sub_link:55:incy"

    res_happ = sub_link_result_kb(55, active_client="happ")
    assert res_happ.inline_keyboard[0][0].callback_data == "sub_link:55:incy"

    res_incy = sub_link_result_kb(55, active_client="incy")
    assert res_incy.inline_keyboard[0][0].callback_data == "sub_link:55:happ"


def test_faq_activation_choice_and_texts():
    kb = faq_activation_choice_kb()
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "faq:activation:happ" in callbacks
    assert "faq:activation:incy" in callbacks

    assert "Happ" in happ_setup_text()
    assert "INCY" in incy_setup_text()
    assert "id6756943388" in incy_setup_text()


def test_subscription_manage_text_omits_raw_link():
    sub = {
        "id": 10,
        "client_email": "12345_main",
        "end_date": "2099-01-01T00:00:00",
        "is_active": 1,
        "display_name": "My Phone",
    }
    raw_link = "happ://crypt3/secret_payload_here"
    txt = subscription_manage_text(sub, raw_link)
    assert raw_link not in txt
    assert "My Phone" in txt

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from bot.keyboards import main_menu_kb, link_email_info_kb, cancel_email_link_kb, unlink_email_confirm_kb
from ui.theme import BTN_POLICY, BTN_REFERRALS_SHORT, BTN_LINK_EMAIL


def test_main_menu_kb_structure():
    # 1. Without linked email
    kb = main_menu_kb()
    # Check rows:
    # row 0: tariffs, manage_sub
    # row 1: faq, support
    # row 2: policy, referrals (single row!)
    # row 3: link email button
    buttons = [[b.text for b in row] for row in kb.inline_keyboard]
    assert [BTN_POLICY, BTN_REFERRALS_SHORT] in buttons
    assert [BTN_LINK_EMAIL] in buttons

    # 2. With linked email
    kb_with_email = main_menu_kb(user_email="test@caelixflow.com")
    buttons_with_email = [[b.text for b in row] for row in kb_with_email.inline_keyboard]
    assert [BTN_POLICY, BTN_REFERRALS_SHORT] in buttons_with_email
    assert ["✉️ test@caelixflow.com"] in buttons_with_email


def test_email_link_keyboards():
    kb_unlinked = link_email_info_kb(user_email=None)
    unlinked_texts = [b.text for row in kb_unlinked.inline_keyboard for b in row]
    assert BTN_LINK_EMAIL in unlinked_texts

    kb_linked = link_email_info_kb(user_email="test@caelixflow.com")
    linked_texts = [b.text for row in kb_linked.inline_keyboard for b in row]
    assert "🔄 Сменить почту" in linked_texts
    assert "❌ Отвязать почту" in linked_texts

    cancel_kb = cancel_email_link_kb()
    assert cancel_kb.inline_keyboard[0][0].text == "❌ Отмена"

    unlink_kb = unlink_email_confirm_kb()
    assert unlink_kb.inline_keyboard[0][0].text == "⚠️ Да, отвязать почту"


@pytest.mark.asyncio
async def test_website_client_mock():
    import httpx

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        # Mock successful send-otp
        mock_post.return_value = httpx.Response(200, json={"ok": True, "message": "Код отправлен"})

        from services.website_client import request_otp_email, verify_otp_email

        res = await request_otp_email(tg_id=12345, email="test@example.com")
        assert res["ok"] is True

        # Mock successful verify-otp
        mock_post.return_value = httpx.Response(200, json={"ok": True, "message": "Почта успешно привязана!"})

        res_v = await verify_otp_email(tg_id=12345, email="test@example.com", code="123456")
        assert res_v["ok"] is True

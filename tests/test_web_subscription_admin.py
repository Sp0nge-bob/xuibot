"""Тесты для просмотра и управления веб-подписками (tg_id=None) в админ-панели."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
from aiogram.types import CallbackQuery, Message

from bot import admin
from bot.admin_keyboards import (
    admin_users_kb,
    admin_users_search_kb,
    admin_user_detail_kb,
    _admin_tg_user_button_label,
)
from bot.admin_users import unique_tg_users_from_subs, group_subscriptions_by_tg
from db.connection import get_db
from db import database as db


@pytest.fixture
def mock_admin(monkeypatch):
    monkeypatch.setattr(admin, "is_admin", lambda uid: True)
    monkeypatch.setattr(admin, "is_debug_admin", lambda uid: True)


@pytest.mark.asyncio
async def test_search_and_get_web_subscriptions_without_tg_id():
    """Проверка, что поиск и списки находят веб-подписки с tg_id IS NULL."""
    async with get_db() as conn:
        # Создаем временную веб-подписку без tg_id (order_id=None чтобы не нарушать FK)
        await conn.execute(
            """INSERT INTO subscriptions (
                tg_id, order_id, client_email, client_uuid, sub_id,
                start_date, end_date, is_active, email_account, display_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                None,
                None,
                "web_unittest_client",
                "uuid_test_123",
                "sub_link_test_123",
                "2026-11-01",
                "2026-12-01",
                "test_web_user@example.com",
                "Web Test Subscription",
            ),
        )
        await conn.commit()

    try:
        # Поиск по email_account
        by_email = await db.search_connected_users("test_web_user@example.com")
        assert len(by_email) >= 1
        found = next(s for s in by_email if s["client_email"] == "web_unittest_client")
        assert found["tg_id"] is None
        assert found["email_account"] == "test_web_user@example.com"

        # Поиск по client_email
        by_client = await db.search_connected_users("web_unittest_client")
        assert any(s["client_email"] == "web_unittest_client" for s in by_client)

        # Проверка get_connected_tg_users
        connected = await db.get_connected_tg_users(limit=100)
        assert any(u.get("client_email") == "web_unittest_client" or u.get("email_account") == "test_web_user@example.com" for u in connected)
    finally:
        async with get_db() as conn:
            await conn.execute("DELETE FROM subscriptions WHERE client_email = 'web_unittest_client'")
            await conn.commit()


def test_unique_users_and_keyboards_for_web_subs():
    """Проверка, что кнопки веб-пользователей не генерируют adm:tg:None."""
    web_sub = {
        "id": 105,
        "subscription_id": 105,
        "tg_id": None,
        "username": None,
        "first_name": None,
        "end_date": "2026-12-31",
        "client_email": "web_abcdef",
        "email_account": "user@test.org",
        "display_name": "Web User Sub",
    }
    grouped = group_subscriptions_by_tg([web_sub])
    assert "web:user@test.org" in grouped

    unique = unique_tg_users_from_subs([web_sub])
    assert len(unique) == 1
    assert unique[0]["tg_id"] is None
    assert unique[0]["subscription_id"] == 105

    label = _admin_tg_user_button_label(unique[0])
    assert "user@test.org" in label
    assert "🌐" in label
    assert "None" not in label

    # Клавиатура списка пользователей
    kb_list = admin_users_kb(unique)
    buttons = [b for row in kb_list.inline_keyboard for b in row]
    user_btn = next(b for b in buttons if b.callback_data.startswith("adm:user:"))
    assert user_btn.callback_data == "adm:user:105"
    assert "adm:tg:None" not in [b.callback_data for b in buttons]

    # Клавиатура результатов поиска
    kb_search = admin_users_search_kb(unique)
    s_buttons = [b for row in kb_search.inline_keyboard for b in row]
    assert s_buttons[0].callback_data == "adm:user:105:search"
    assert "adm:tg:None" not in [b.callback_data for b in s_buttons]


def test_admin_user_detail_kb_handles_none_tg_id():
    """Проверка детальной клавиатуры подписки без tg_id."""
    kb = admin_user_detail_kb(
        subscription_id=105,
        tg_id=None,
        from_picker=True,  # Даже если from_picker=True, при tg_id=None возврат не должен быть adm:tg:None
    )
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]

    assert "adm:tg:None" not in callbacks
    assert "adm:trial_reset:None" not in callbacks
    # Кнопка назад должна вести к списку пользователей
    assert "adm:users" in callbacks
    # Кнопка удаления должна присутствовать
    assert "adm:del_sub:105" in callbacks


@pytest.mark.asyncio
async def test_cb_admin_tg_user_safe_rejection(mock_admin):
    """adm:tg:None или некорректный ID не должен вызывать зависание спиннера."""
    cb = CallbackQuery.model_construct(
        data="adm:tg:None",
        from_user=SimpleNamespace(id=1),
    )
    state = AsyncMock()
    answered = []

    async def mock_answer(cb_obj, text="", show_alert=False):
        answered.append((text, show_alert))

    with patch.object(admin, "safe_cb_answer", side_effect=mock_answer):
        await admin.cb_admin_tg_user(cb, state)

    assert len(answered) == 1
    assert "не привязан" in answered[0][0]
    assert answered[0][1] is True


@pytest.mark.asyncio
async def test_cb_admin_trial_reset_confirm_safe_rejection(mock_admin):
    """adm:trial_reset:None не должен выбрасывать исключение и зависать."""
    cb = CallbackQuery.model_construct(
        data="adm:trial_reset:None",
        from_user=SimpleNamespace(id=1),
    )
    answered = []

    async def mock_answer(cb_obj, text="", show_alert=False):
        answered.append((text, show_alert))

    with patch.object(admin, "safe_cb_answer", side_effect=mock_answer):
        await admin.cb_admin_trial_reset_confirm(cb)

    assert len(answered) == 1
    assert "не привязан" in answered[0][0]


@pytest.mark.asyncio
async def test_show_admin_user_sub_detail_with_none_tg_id(mock_admin, monkeypatch):
    """Проверка отображения карточки веб-подписки с tg_id=None."""
    sub = {
        "id": 888,
        "tg_id": None,
        "is_active": 1,
        "client_email": "web_test888",
        "email_account": "customer@site.ru",
        "display_name": "Web Sub #888",
        "end_date": "2026-12-31",
        "sub_id": "test_sub_link_888",
    }
    monkeypatch.setattr(admin.db, "get_subscription_by_id", AsyncMock(return_value=sub))
    monkeypatch.setattr(admin.db, "get_paid_orders_for_subscription", AsyncMock(return_value=[]))
    monkeypatch.setattr(admin, "enrich_order_with_referrer", AsyncMock(return_value=None))
    monkeypatch.setattr(admin.promo_db, "find_grant_use_heuristic_for_subscription", AsyncMock(return_value=None))
    monkeypatch.setattr(admin, "get_client_network_data", AsyncMock(return_value=None))

    render = AsyncMock()
    monkeypatch.setattr(admin, "send_or_edit", render)
    monkeypatch.setattr(admin, "safe_cb_answer", AsyncMock())

    state = AsyncMock()
    state.get_data.return_value = {"admin_user_picker_tg_id": None}

    cb = CallbackQuery.model_construct(data="adm:user:888", from_user=SimpleNamespace(id=1))
    await admin.cb_admin_user_detail(cb, state)

    text, kb = render.await_args.args[1:]
    assert "Web Sub #888" in text
    assert "web_test888" in text

    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "adm:tg:None" not in callbacks
    assert "adm:trial_reset:None" not in callbacks

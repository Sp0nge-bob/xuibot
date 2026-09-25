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


        # Mock successful unlink-email
        mock_post.return_value = httpx.Response(200, json={"ok": True, "message": "Почта успешно отвязана"})
        from services.website_client import unlink_email_account
        res_u = await unlink_email_account(tg_id=12345)
        assert res_u["ok"] is True


@pytest.mark.asyncio
async def test_unlink_email_fallback_subscription_separation():
    import aiosqlite
    from contextlib import asynccontextmanager
    from services.website_client import unlink_email_account

    test_db_path = "file:mem_test_unlink?mode=memory&cache=shared"
    # Keep master connection open so the shared memory database persists across connections
    master_conn = await aiosqlite.connect(test_db_path, uri=True)
    async with aiosqlite.connect(test_db_path, uri=True) as db:
        await db.execute("""
            CREATE TABLE email_accounts (
                email TEXT PRIMARY KEY,
                tg_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0,
                block_reason TEXT DEFAULT '',
                blocked_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                email TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                order_id INTEGER,
                inbound_id INTEGER,
                client_email TEXT,
                client_uuid TEXT,
                sub_id TEXT,
                start_date TIMESTAMP,
                end_date TIMESTAMP,
                traffic_limit_gb INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                display_name TEXT,
                email_account TEXT,
                origin TEXT DEFAULT 'bot'
            )
        """)
        await db.execute("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT DEFAULT 'bot'
            )
        """)

        test_tg = 99881122
        test_mail = "bot_unlink_test@example.com"

        await db.execute("INSERT INTO email_accounts (email, tg_id) VALUES (?, ?)", (test_mail, test_tg))
        await db.execute("INSERT INTO users (tg_id, email) VALUES (?, ?)", (test_tg, test_mail))

        cur1 = await db.execute(
            """INSERT INTO subscriptions (tg_id, email_account, origin, is_active, display_name, start_date, end_date)
               VALUES (?, ?, 'web', 1, 'Web Sub', '2026-01-01', '2026-12-31')""",
            (test_tg, test_mail),
        )
        web_sub_id = cur1.lastrowid

        cur2 = await db.execute(
            """INSERT INTO subscriptions (tg_id, email_account, origin, is_active, display_name, start_date, end_date)
               VALUES (?, ?, 'bot', 1, 'Bot Sub', '2026-01-01', '2026-12-31')""",
            (test_tg, test_mail),
        )
        bot_sub_id = cur2.lastrowid
        await db.commit()

    @asynccontextmanager
    async def temp_get_db():
        async with aiosqlite.connect(test_db_path, uri=True) as db:
            yield db

    try:
        with patch("httpx.AsyncClient.post", side_effect=Exception("Website offline")), \
             patch("db.connection.get_db", temp_get_db):
            res = await unlink_email_account(test_tg)
            assert res["ok"] is True

        async with aiosqlite.connect(test_db_path, uri=True) as db:
            # Check web sub: tg_id is NULL, email_account is test_mail
            async with db.execute("SELECT tg_id, email_account FROM subscriptions WHERE id = ?", (web_sub_id,)) as cur:
                w_row = await cur.fetchone()
                assert w_row[0] is None
                assert w_row[1] == test_mail

            # Check bot sub: tg_id is test_tg, email_account is NULL
            async with db.execute("SELECT tg_id, email_account FROM subscriptions WHERE id = ?", (bot_sub_id,)) as cur:
                b_row = await cur.fetchone()
                assert b_row[0] == test_tg
                assert b_row[1] is None

            # Check email_accounts and users
            async with db.execute("SELECT tg_id FROM email_accounts WHERE email = ?", (test_mail,)) as cur:
                ea_row = await cur.fetchone()
                assert ea_row[0] is None
            async with db.execute("SELECT email FROM users WHERE tg_id = ?", (test_tg,)) as cur:
                u_row = await cur.fetchone()
                assert u_row[0] is None
    finally:
        await master_conn.close()

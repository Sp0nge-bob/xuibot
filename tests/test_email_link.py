from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from bot.keyboards import main_menu_kb, link_email_info_kb, cancel_email_link_kb, unlink_email_confirm_kb
from ui.theme import BTN_POLICY, BTN_REFERRALS_SHORT, BTN_LINK_EMAIL, BTN_HELP_HUB


def test_main_menu_kb_structure():
    # 1. Without linked email
    kb = main_menu_kb()
    buttons = [[b.text for b in row] for row in kb.inline_keyboard]
    assert [BTN_HELP_HUB, BTN_REFERRALS_SHORT] in buttons
    assert [BTN_POLICY, BTN_LINK_EMAIL] in buttons

    # 2. With linked email
    kb_with_email = main_menu_kb(user_email="test@caelixflow.com")
    buttons_with_email = [[b.text for b in row] for row in kb_with_email.inline_keyboard]
    assert [BTN_HELP_HUB, BTN_REFERRALS_SHORT] in buttons_with_email
    assert [BTN_POLICY, "✉️ test@caelixflow.com"] in buttons_with_email


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


@pytest.mark.asyncio
async def test_link_telegram_token_http_failure_fallback():
    import aiosqlite
    import httpx
    from datetime import datetime, timezone, timedelta
    from contextlib import asynccontextmanager
    from services.website_client import link_telegram_token

    test_db_path = "file:mem_test_link_token?mode=memory&cache=shared"
    master_conn = await aiosqlite.connect(test_db_path, uri=True)
    async with aiosqlite.connect(test_db_path, uri=True) as db:
        await db.execute("""
            CREATE TABLE telegram_link_tokens (
                token TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE email_accounts (
                email TEXT PRIMARY KEY,
                tg_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE users (
                tg_id INTEGER PRIMARY KEY,
                email TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER,
                email_account TEXT
            )
        """)

        token_str = "tok_test_12345"
        email_str = "user_link@example.com"
        exp_iso = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        await db.execute(
            "INSERT INTO telegram_link_tokens (token, email, expires_at, used) VALUES (?, ?, ?, 0)",
            (token_str, email_str, exp_iso),
        )
        await db.execute("INSERT INTO email_accounts (email, tg_id) VALUES (?, NULL)", (email_str,))
        await db.execute("INSERT INTO users (tg_id, email) VALUES (778899, NULL)")
        await db.execute("INSERT INTO subscriptions (tg_id, email_account) VALUES (NULL, ?)", (email_str,))
        await db.commit()

    @asynccontextmanager
    async def temp_get_db():
        async with aiosqlite.connect(test_db_path, uri=True) as db:
            yield db

    try:
        # Mock HTTP returning 401 (e.g. from wrong port or unauthorized proxy)
        with patch("httpx.AsyncClient.post", return_value=httpx.Response(401, text="Unauthorized")), \
             patch("db.connection.get_db", temp_get_db):
            res = await link_telegram_token(token=token_str, tg_id=778899)
            assert res["ok"] is True
            assert res["email"] == email_str

        async with aiosqlite.connect(test_db_path, uri=True) as db:
            # Token marked as used
            async with db.execute("SELECT used FROM telegram_link_tokens WHERE token = ?", (token_str,)) as cur:
                assert (await cur.fetchone())[0] == 1
            # Email accounts updated
            async with db.execute("SELECT tg_id FROM email_accounts WHERE email = ?", (email_str,)) as cur:
                assert (await cur.fetchone())[0] == 778899
            # Users updated
            async with db.execute("SELECT email FROM users WHERE tg_id = 778899") as cur:
                assert (await cur.fetchone())[0] == email_str
            # Subscriptions updated
            async with db.execute("SELECT tg_id FROM subscriptions WHERE email_account = ?", (email_str,)) as cur:
                assert (await cur.fetchone())[0] == 778899
    finally:
        await master_conn.close()


def test_candidate_urls_priority():
    from services.website_client import get_candidate_base_urls
    candidates = get_candidate_base_urls()
    assert "http://127.0.0.1:8090" in candidates
    assert "http://127.0.0.1:8080" not in candidates


def test_build_happ_redirect_url():
    from config.settings import settings
    from services.happ_crypto import build_happ_redirect_url

    # 1. WEBSITE_PUBLIC_URL
    with patch.object(settings, "WEBSITE_PUBLIC_URL", "https://site.example.com"), \
         patch.object(settings, "WEBSITE_URL", ""), \
         patch.object(settings, "WEBSITE_DOMAIN", ""):
        url = build_happ_redirect_url("abc-123")
        assert url == "https://site.example.com/happ/abc-123"

    # 2. WEBSITE_URL
    with patch.object(settings, "WEBSITE_PUBLIC_URL", ""), \
         patch.object(settings, "WEBSITE_URL", "https://site-url.com/some/path"), \
         patch.object(settings, "WEBSITE_DOMAIN", ""):
        url = build_happ_redirect_url("xyz")
        assert url == "https://site-url.com/happ/xyz"

    # 3. WEBSITE_DOMAIN (raw domain without protocol)
    with patch.object(settings, "WEBSITE_PUBLIC_URL", ""), \
         patch.object(settings, "WEBSITE_URL", ""), \
         patch.object(settings, "WEBSITE_DOMAIN", "portal.caelixflow.com"):
        url = build_happ_redirect_url(100)
        assert url == "https://portal.caelixflow.com/happ/100"

    # 4. Fallback to PUBLIC_WEBHOOK_URL if no website domain is set
    with patch.object(settings, "WEBSITE_PUBLIC_URL", ""), \
         patch.object(settings, "WEBSITE_URL", ""), \
         patch.object(settings, "WEBSITE_DOMAIN", ""), \
         patch.object(settings, "PUBLIC_WEBHOOK_URL", "https://mirror.example.com/platega-webhook"):
        url = build_happ_redirect_url(42)
        assert url == "https://mirror.example.com/happ/42"

    # 5. Fallback to default
    with patch.object(settings, "WEBSITE_PUBLIC_URL", ""), \
         patch.object(settings, "WEBSITE_URL", ""), \
         patch.object(settings, "WEBSITE_DOMAIN", ""), \
         patch.object(settings, "PUBLIC_WEBHOOK_URL", ""), \
         patch.object(settings, "SUBSCRIPTION_BASE_URL", ""):
        url = build_happ_redirect_url("def")
        assert url == "https://caelixflow.com/happ/def"


@pytest.mark.asyncio
async def test_email_bonus_lifecycle():
    from db import bot_settings as bot_settings_db
    from db.database import apply_email_link_bonus, is_email_bonus_eligible, init_db
    from db.connection import get_db

    await init_db()
    await bot_settings_db.init_bot_settings()

    # Default settings
    await bot_settings_db.set_email_bonus_enabled(False)
    await bot_settings_db.set_email_bonus_days(5)
    assert await bot_settings_db.get_email_bonus_enabled() is False
    assert await bot_settings_db.get_email_bonus_days() == 5

    test_user_id = 999111222
    # Ensure user exists in users table with email_bonus_granted = 0
    async with get_db() as db:
        await db.execute("DELETE FROM users WHERE tg_id = ?", (test_user_id,))
        await db.execute("DELETE FROM subscriptions WHERE tg_id = ?", (test_user_id,))
        await db.execute("INSERT INTO users (tg_id, email_bonus_granted) VALUES (?, 0)", (test_user_id,))
        await db.execute(
            """INSERT INTO subscriptions (tg_id, client_email, end_date, is_active)
               VALUES (?, 'client_sub_1@vpn.com', '2026-10-01T00:00:00+00:00', 1)""",
            (test_user_id,),
        )
        await db.commit()

    assert await is_email_bonus_eligible(test_user_id) is True

    # 1. When bonus is disabled, nothing granted
    granted = await apply_email_link_bonus(test_user_id)
    assert granted == 0
    assert await is_email_bonus_eligible(test_user_id) is True

    # 2. When bonus is enabled, grants 5 days and marks user as granted
    await bot_settings_db.set_email_bonus_enabled(True)
    with patch("services.xui.get_unified_panel_client", return_value=None):
        granted = await apply_email_link_bonus(test_user_id)
    assert granted == 5

    # Check that user is no longer eligible
    assert await is_email_bonus_eligible(test_user_id) is False

    # Check subscription end_date was extended
    async with get_db() as db:
        async with db.execute("SELECT end_date FROM subscriptions WHERE tg_id = ?", (test_user_id,)) as cur:
            row = await cur.fetchone()
            assert row[0].startswith("2026-10-06")

    # 3. Second call returns 0 (cannot double-dip)
    with patch("services.xui.get_unified_panel_client", return_value=None):
        granted_again = await apply_email_link_bonus(test_user_id)
    assert granted_again == 0


def test_payment_admin_notify_sources():
    from services.payment_alerts import format_payment_admin_notify_text

    # 1. Bot order
    bot_order = {
        "id": 101,
        "tg_id": 123456,
        "plan_name": "1 месяц",
        "amount": 199,
        "platega_tx_id": "tx-bot-123",
        "order_type": "extend",
        "source": "bot",
        "customer_email": "user@vpn.com",
    }
    user = {"username": "testuser", "first_name": "Test"}
    bot_text = format_payment_admin_notify_text(bot_order, user)
    assert "📱 Источник: <b>🤖 Бот</b>" in bot_text
    assert "@testuser" in bot_text
    assert "✉️ Email: <code>user@vpn.com</code>" in bot_text
    assert "<b>199 ₽</b>" in bot_text
    assert "🔄 Тип: <b>Продление</b>" in bot_text

    # 2. Web order without linked Telegram
    web_order = {
        "id": 102,
        "tg_id": 0,
        "plan_name": "3 месяца",
        "amount": 499,
        "platega_tx_id": "tx-web-456",
        "order_type": "new",
        "source": "web",
        "customer_email": "webuser@example.com",
    }
    web_text = format_payment_admin_notify_text(web_order, None)
    assert "📱 Источник: <b>🌐 Сайт</b>" in web_text
    assert "Веб-пользователь" in web_text
    assert "✉️ Email: <code>webuser@example.com</code>" in web_text
    assert "<b>499 ₽</b>" in web_text
    assert "🔄 Тип: <b>Новая подписка</b>" in web_text



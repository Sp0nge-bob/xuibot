"""Тесты секции «Документы и инструкции» в .env, ioshappblocked и миграции ссылок из БД."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from bot.keyboards import faq_activation_choice_kb, faq_activation_client_nav_kb
from bot.messages import subscription_manage_text
from config.legal import (
    DEFAULT_IOS_HAPP_BLOCKED_URL,
    DEFAULT_PRIVACY_POLICY_URL,
    DEFAULT_REFUND_POLICY_URL,
    DEFAULT_TERMS_OF_SERVICE_URL,
    env_file_has_documents_section,
)
from config.settings import Settings, settings
from db import bot_settings as settings_db
from db import connection as db_conn
from services.fulfillment import _success_text
from services.fulfillment_text import (
    activation_setup_body,
    get_ios_happ_blocked_url,
    happ_setup_body,
    incy_setup_body,
)


def _kb_urls(kb) -> list[str]:
    urls: list[str] = []
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "url", None):
                urls.append(btn.url)
    return urls


def _kb_texts(kb) -> list[str]:
    texts: list[str] = []
    for row in kb.inline_keyboard:
        for btn in row:
            if getattr(btn, "text", None):
                texts.append(btn.text)
    return texts


def test_settings_accepts_lowercase_ioshappblocked():
    s = Settings(
        BOT_TOKEN="0:test",
        PLATEGA_MERCHANT_ID="00000000-0000-0000-0000-000000000000",
        PLATEGA_SECRET="sec",
        XUI_HOST="https://example.test/",
        ioshappblocked="https://custom.example/ios-guide",
        privacy_policy_url="https://custom.example/privacy",
        terms_of_service_url="https://custom.example/terms",
        refund_policy_url="https://custom.example/refund",
    )
    assert s.IOSHAPPBLOCKED == "https://custom.example/ios-guide"
    assert s.PRIVACY_POLICY_URL == "https://custom.example/privacy"
    assert s.TERMS_OF_SERVICE_URL == "https://custom.example/terms"
    assert s.REFUND_POLICY_URL == "https://custom.example/refund"


def test_ioshappblocked_unset_hides_blocked_mentions_and_buttons(monkeypatch):
    monkeypatch.setattr(settings, "IOSHAPPBLOCKED", "")
    assert get_ios_happ_blocked_url() == ""

    happ_text = happ_setup_body()
    incy_text = incy_setup_body()
    act_text = activation_setup_body()
    sub_text = subscription_manage_text(
        {
            "id": 1,
            "sub_id": "abcdefgh12345678",
            "plan_name": "1 месяц",
            "end_date": (datetime.utcnow() + timedelta(days=20)).isoformat(),
            "client_email": "tg12345",
            "traffic_limit_gb": 0,
            "is_active": 1,
        },
        "https://sub.example/123",
    )
    cap_text = _success_text(
        title="Оплата прошла успешно!",
        plan={"id": "1m", "name": "1 месяц", "days": 30, "price": 300, "traffic_gb": 0},
        end_date="2027-01-01",
        sub_link="https://sub.example/123",
        client_email="tg12345",
        display_name="Подписка #1",
        is_test=False,
        inbound_count=3,
        limit_ip=3,
    )

    for text in (happ_text, incy_text, act_text, sub_text, cap_text):
        assert "недоступен в российском App Store" not in text
        assert "недоступен в РФ" not in text
        assert "Смена региона" not in text
        assert "смене региона" not in text

    kb_choice = faq_activation_choice_kb()
    kb_nav = faq_activation_client_nav_kb(client="happ")
    assert all("Смена региона" not in t for t in _kb_texts(kb_choice))
    assert all("Смена региона" not in t for t in _kb_texts(kb_nav))


def test_ioshappblocked_set_shows_notice_and_buttons_with_custom_url(monkeypatch):
    custom_guide = "https://docs.example.org/ios-region-change"
    monkeypatch.setattr(settings, "IOSHAPPBLOCKED", custom_guide)
    assert get_ios_happ_blocked_url() == custom_guide

    happ_text = happ_setup_body()
    incy_text = incy_setup_body()
    act_text = activation_setup_body()
    sub_text = subscription_manage_text(
        {
            "id": 1,
            "sub_id": "abcdefgh12345678",
            "plan_name": "1 месяц",
            "end_date": (datetime.utcnow() + timedelta(days=20)).isoformat(),
            "client_email": "tg12345",
            "traffic_limit_gb": 0,
            "is_active": 1,
        },
        "https://sub.example/123",
    )
    cap_text = _success_text(
        title="Оплата прошла успешно!",
        plan={"id": "1m", "name": "1 месяц", "days": 30, "price": 300, "traffic_gb": 0},
        end_date="2027-01-01",
        sub_link="https://sub.example/123",
        client_email="tg12345",
        display_name="Подписка #1",
        is_test=False,
        inbound_count=3,
        limit_ip=3,
    )

    for text in (happ_text, act_text, sub_text, cap_text):
        assert custom_guide in text
        assert "App Store" in text
    assert "без смены региона" in incy_text

    kb_choice = faq_activation_choice_kb()
    kb_nav = faq_activation_client_nav_kb(client="happ")
    assert custom_guide in _kb_urls(kb_choice)
    assert custom_guide in _kb_urls(kb_nav)


@pytest.mark.asyncio
async def test_startup_migrates_existing_db_documents_into_env_file(monkeypatch):
    tmp_dir = Path(".test_tmp") / "test_docs_migration"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        db_file = tmp_dir / "bot_docs.db"
        env_file = tmp_dir / ".env"
        env_file.write_text("BOT_TOKEN=0:test\nXUI_HOST=https://xui.example/\n", encoding="utf-8")

        await db_conn.close_connection()
        monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
        settings_db._settings_cache.clear()

        # Инициализируем таблицу и имитируем ранее сохранённые в боте кастомные ссылки
        async with db_conn.get_db() as db:
            await db.execute(
                """CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            await db.commit()

        await settings_db.set_setting(
            settings_db.SETTING_PRIVACY_POLICY_URL, "https://old-bot.example/privacy"
        )
        await settings_db.set_setting(
            settings_db.SETTING_TERMS_OF_SERVICE_URL, "https://old-bot.example/terms"
        )
        await settings_db.set_setting(
            settings_db.SETTING_REFUND_POLICY_URL, "https://old-bot.example/refund"
        )
        monkeypatch.setattr(settings, "IOSHAPPBLOCKED", "")

        assert not env_file_has_documents_section(env_file)

        # Запускаем миграцию при старте
        await settings_db._sync_documents_with_env_on_startup(env_path=env_file)

        assert env_file_has_documents_section(env_file)
        env_content = env_file.read_text(encoding="utf-8")
        assert "# --- Документы и инструкции ---" in env_content
        assert "PRIVACY_POLICY_URL=https://old-bot.example/privacy" in env_content
        assert "TERMS_OF_SERVICE_URL=https://old-bot.example/terms" in env_content
        assert "REFUND_POLICY_URL=https://old-bot.example/refund" in env_content
        assert f"ioshappblocked={DEFAULT_IOS_HAPP_BLOCKED_URL}" in env_content

        assert await settings_db.get_privacy_policy_url() == "https://old-bot.example/privacy"
        assert await settings_db.get_terms_of_service_url() == "https://old-bot.example/terms"
        assert await settings_db.get_refund_policy_url() == "https://old-bot.example/refund"
    finally:
        await db_conn.close_connection()
        monkeypatch.setattr(settings, "PRIVACY_POLICY_URL", DEFAULT_PRIVACY_POLICY_URL)
        monkeypatch.setattr(settings, "TERMS_OF_SERVICE_URL", DEFAULT_TERMS_OF_SERVICE_URL)
        monkeypatch.setattr(settings, "REFUND_POLICY_URL", DEFAULT_REFUND_POLICY_URL)
        monkeypatch.setattr(settings, "IOSHAPPBLOCKED", "")
        shutil.rmtree(tmp_dir, ignore_errors=True)

"""Тесты поддержки прокси для Telegram API."""
import os
import pytest
from config.settings import Settings
from bot.session import mask_proxy, ResilientAiohttpSession


def test_effective_telegram_proxy(monkeypatch):
    # Явно заданный TELEGRAM_PROXY
    s1 = Settings(
        BOT_TOKEN="123:test",
        TELEGRAM_PROXY="socks5://127.0.0.1:10808",
        PLATEGA_MERCHANT_ID="m",
        PLATEGA_SECRET="s",
        SECRET_KEY="k" * 32,
    )
    assert s1.effective_telegram_proxy == "socks5://127.0.0.1:10808"

    # Пустой TELEGRAM_PROXY с fallback на HTTPS_PROXY
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.local:8080")
    s2 = Settings(
        BOT_TOKEN="123:test",
        TELEGRAM_PROXY="",
        PLATEGA_MERCHANT_ID="m",
        PLATEGA_SECRET="s",
        SECRET_KEY="k" * 32,
    )
    assert s2.effective_telegram_proxy == "http://proxy.local:8080"

    # Если всё пусто
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("TELEGRAM_PROXY", raising=False)
    monkeypatch.delenv("telegram_proxy", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    s3 = Settings(
        BOT_TOKEN="123:test",
        TELEGRAM_PROXY="",
        PLATEGA_MERCHANT_ID="m",
        PLATEGA_SECRET="s",
        SECRET_KEY="k" * 32,
    )
    assert s3.effective_telegram_proxy is None


def test_mask_proxy():
    assert mask_proxy("socks5://user:super_secret@1.2.3.4:10808") == "socks5://user:***@1.2.3.4:10808"
    assert mask_proxy("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert mask_proxy("") == ""


@pytest.mark.asyncio
async def test_resilient_session_with_proxy():
    session = ResilientAiohttpSession(proxy="socks5://127.0.0.1:10808")
    assert session._proxy == "socks5://127.0.0.1:10808"
    client_sess = await session.create_session()
    assert client_sess is not None
    await client_sess.close()

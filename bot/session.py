"""Устойчивая aiohttp-сессия к api.telegram.org с поддержкой IPv4 и прокси."""
from __future__ import annotations

import socket
import urllib.parse
from typing import Any

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from loguru import logger

_FAST_UI_METHODS = frozenset({
    "editMessageText",
    "editMessageCaption",
    "editMessageReplyMarkup",
    "sendMessage",
    "sendPhoto",
    "answerCallbackQuery",
    "getMe",
})


def mask_proxy(url: str) -> str:
    """Маскирует пароль в proxy URL для безопасного логирования."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return url


class ResilientAiohttpSession(AiohttpSession):
    """
    Устойчивая сессия к api.telegram.org:
    - Форсирует IPv4 (AF_INET), исключая 10-секундные зависания на битых IPv6 маршрутах VPS.
    - Очищает закрытые keep-alive сокеты (enable_cleanup_closed=True, keepalive_timeout=20s).
    - Для быстрых UI-запросов (editMessageText, sendMessage, answerCallbackQuery и др.)
      ограничивает таймаут попытки 7 секундами и делает мгновенный повтор при залипшем сокете.
    - Поддерживает работу через HTTP / HTTPS / SOCKS5 прокси.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(timeout=25.0, **kwargs)
        self._connector_init["family"] = socket.AF_INET
        self._connector_init["enable_cleanup_closed"] = True
        self._connector_init["keepalive_timeout"] = 20.0

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        api_method = getattr(method, "__api_method__", "")
        if api_method in _FAST_UI_METHODS and timeout is None:
            try:
                return await super().make_request(bot, method, timeout=7)
            except TelegramNetworkError as exc:
                logger.warning(
                    "Telegram API {} network stall ({}), retrying immediately…",
                    api_method,
                    exc,
                )
                return await super().make_request(bot, method, timeout=10)
        return await super().make_request(bot, method, timeout=timeout)

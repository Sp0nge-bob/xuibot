"""Блокировка действий пользователей, пока ★ Primary недоступна."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.ui_helpers import safe_cb_answer
from services.primary_gate import SERVICE_UNAVAILABLE_TEXT, is_primary_operational


class PrimaryGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not await is_primary_operational():
            if isinstance(event, CallbackQuery):
                await safe_cb_answer(
                    event,
                    "Сервис временно недоступен. Панель VPN на обслуживании.",
                    show_alert=True,
                )
                try:
                    if event.message:
                        await event.message.answer(SERVICE_UNAVAILABLE_TEXT)
                except Exception:
                    pass
            elif isinstance(event, Message):
                await event.answer(SERVICE_UNAVAILABLE_TEXT)
            return None
        return await handler(event, data)
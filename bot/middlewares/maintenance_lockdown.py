"""Единая блокировка: ручная + ★ Primary недоступна."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.keyboards import lockdown_support_kb
from bot.ui_helpers import safe_cb_answer
from services.bot_lockdown import (
    get_block_response,
    is_support_interaction_allowed,
    is_user_allowed,
)


class MaintenanceLockdownMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        if await is_user_allowed(user.id):
            return await handler(event, data)

        block = await get_block_response()
        if block is None:
            return await handler(event, data)

        if await is_support_interaction_allowed(event, data):
            return await handler(event, data)

        alert_text, message_text = block
        kb = lockdown_support_kb()
        if isinstance(event, CallbackQuery):
            await safe_cb_answer(event, alert_text, show_alert=True)
            try:
                if event.message:
                    await event.message.answer(message_text, reply_markup=kb)
            except Exception:
                pass
        elif isinstance(event, Message):
            await event.answer(message_text, reply_markup=kb)
        return None
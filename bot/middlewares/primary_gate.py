"""Блокировка действий пользователей, пока ★ Primary недоступна."""
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.admin_auth import is_admin
from bot.ui_helpers import safe_cb_answer
from services.primary_gate import SERVICE_UNAVAILABLE_TEXT, is_primary_operational

_ADMIN_STATE_PREFIXES = ("AdminStates:", "AdminPricingStates:")


async def _admin_panel_allowed(event: TelegramObject, data: dict[str, Any]) -> bool:
    user = getattr(event, "from_user", None)
    if not user or not is_admin(user.id):
        return False

    if isinstance(event, CallbackQuery):
        return (event.data or "").startswith("adm:")

    if isinstance(event, Message):
        raw = (event.text or "").strip()
        if raw:
            cmd = raw.split()[0].split("@")[0].lower()
            if cmd == "/admin":
                return True

        state: FSMContext | None = data.get("state")
        if state:
            current = await state.get_state()
            if current and current.startswith(_ADMIN_STATE_PREFIXES):
                return True

    return False


class PrimaryGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if await _admin_panel_allowed(event, data):
            return await handler(event, data)

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
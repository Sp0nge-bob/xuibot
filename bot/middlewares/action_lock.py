"""Защита от наложения действий: один обработчик на пользователя + debounce кнопок."""
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger

from bot.ui_helpers import safe_cb_answer
from config.settings import settings


class ActionLockMiddleware(BaseMiddleware):
    """
    Блокирует параллельные callback/message от одного пользователя.

    - Пока выполняется handler, повторные нажатия отклоняются.
    - Одинаковый callback_data в течение debounce — тихо игнорируется.
    """

    def __init__(
        self,
        *,
        debounce_sec: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._debounce_sec = (
            debounce_sec if debounce_sec is not None else settings.BOT_ACTION_DEBOUNCE_SEC
        )
        self._enabled = enabled if enabled is not None else settings.BOT_ACTION_LOCK_ENABLED
        self._processing: set[int] = set()
        self._last_callback: dict[int, tuple[str, float]] = {}

    @staticmethod
    def _user_id(event: TelegramObject) -> int | None:
        user = getattr(event, "from_user", None)
        return user.id if user else None

    async def _reject_busy_callback(self, cb: CallbackQuery) -> None:
        await safe_cb_answer(
            cb,
            "⏳ Подождите, предыдущее действие ещё выполняется",
            show_alert=False,
        )

    async def _reject_debounce_callback(self, cb: CallbackQuery) -> None:
        await safe_cb_answer(cb)

    async def _reject_busy_message(self, message: Message) -> None:
        await message.answer("⏳ Подождите, предыдущее действие ещё выполняется")

    def _should_debounce_callback(self, user_id: int, data: str) -> bool:
        now = time.monotonic()
        prev = self._last_callback.get(user_id)
        if prev and prev[0] == data and now - prev[1] < self._debounce_sec:
            return True
        self._last_callback[user_id] = (data, now)
        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self._enabled:
            return await handler(event, data)

        user_id = self._user_id(event)
        if user_id is None:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if self._should_debounce_callback(user_id, cb_data):
                logger.debug("Debounce callback {} от user {}", cb_data, user_id)
                await self._reject_debounce_callback(event)
                return None

        if user_id in self._processing:
            logger.debug("Занятый user {} — событие пропущено", user_id)
            if isinstance(event, CallbackQuery):
                await self._reject_busy_callback(event)
            elif isinstance(event, Message):
                await self._reject_busy_message(event)
            return None

        self._processing.add(user_id)
        try:
            return await handler(event, data)
        finally:
            self._processing.discard(user_id)
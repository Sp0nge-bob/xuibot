"""Защита от наложения действий: один обработчик на пользователя + debounce кнопок."""
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from loguru import logger

from bot.priority_commands import is_priority_reboot_message
from bot.ui_helpers import safe_cb_answer
from config.settings import settings


_NAVIGATION_COMMANDS = frozenset({
    "/start",
    "/menu",
    "/subscription",
    "/faq",
    "/admin",
    "/help",
    "/support",
    "/cancel",
})

_NAVIGATION_CALLBACKS = frozenset({
    "main_menu",
    "manage_sub",
    "tariffs",
    "purchase_plans",
    "help_hub",
    "project_policy",
    "faq_menu",
    "support",
    "referral_program",
    "link_email_menu",
    "promo_enter",
    "purchase_promo",
    "extend_promo",
    "trial_offer",
    "extend_menu",
    "admin_menu",
})

_NAVIGATION_CALLBACK_PREFIXES = (
    "faq_cat:",
    "faq_item:",
    "faq_back:",
    "select_plan:",
    "manage_sub:",
    "sub_info:",
    "adm:menu",
    "adm:back",
)

_MUTATING_LOCK_MAX_HOLD_SEC = 12.0


def _is_navigation_event(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        text = (event.text or "").strip()
        if not text.startswith("/"):
            return False
        cmd = text.split()[0].split("@")[0].lower()
        return cmd in _NAVIGATION_COMMANDS
    if isinstance(event, CallbackQuery):
        cb_data = (event.data or "").strip()
        if cb_data in _NAVIGATION_CALLBACKS:
            return True
        return cb_data.startswith(_NAVIGATION_CALLBACK_PREFIXES)
    return False


class ActionLockMiddleware(BaseMiddleware):
    """
    Блокирует параллельные мутирующие действия от одного пользователя + debounce кнопок.

    - Одинаковый callback_data в течение debounce — тихо игнорируется.
    - Навигационные команды (/start, /subscription, /faq, /admin) и кнопки меню (main_menu и др.)
      не блокируются зависшими навигационными запросами.
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
        self._processing_since: dict[int, float] = {}
        self._processing_is_nav: dict[int, bool] = {}
        self._processing_token: dict[int, int] = {}
        self._token_seq: int = 0
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

    def _trim_debounce_cache(self) -> None:
        max_entries = int(settings.BOT_ACTION_DEBOUNCE_MAX_ENTRIES)
        if len(self._last_callback) <= max_entries:
            return
        now = time.monotonic()
        stale = [
            uid for uid, (_, ts) in self._last_callback.items()
            if now - ts > self._debounce_sec * 10
        ]
        for uid in stale:
            self._last_callback.pop(uid, None)
        while len(self._last_callback) > max_entries:
            self._last_callback.pop(next(iter(self._last_callback)))

    def _should_debounce_callback(self, user_id: int, data: str) -> bool:
        now = time.monotonic()
        prev = self._last_callback.get(user_id)
        if prev and prev[0] == data and now - prev[1] < self._debounce_sec:
            return True
        self._last_callback[user_id] = (data, now)
        self._trim_debounce_cache()
        return False

    def release_user(self, user_id: int) -> None:
        """Снять блокировку пользователя."""
        self._processing.discard(user_id)
        self._processing_since.pop(user_id, None)
        self._processing_is_nav.pop(user_id, None)
        self._processing_token.pop(user_id, None)

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

        # /reboot у админа: абсолютный приоритет, снимает зависшую блокировку
        if isinstance(event, Message) and is_priority_reboot_message(event):
            self.release_user(user_id)
            logger.warning("Priority /reboot от user {} — обход ActionLock", user_id)
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if self._should_debounce_callback(user_id, cb_data):
                logger.debug("Debounce callback {} от user {}", cb_data, user_id)
                await self._reject_debounce_callback(event)
                return None

        is_nav = _is_navigation_event(event)
        if user_id in self._processing:
            started_at = self._processing_since.get(user_id, 0.0)
            elapsed = time.monotonic() - started_at
            prev_is_nav = self._processing_is_nav.get(user_id, False)
            # Если предыдущее действие тоже было обычной навигацией ИЛИ зависло дольше порога —
            # пропускаем новое действие без блокировки пользователя.
            if (is_nav and prev_is_nav) or elapsed > _MUTATING_LOCK_MAX_HOLD_SEC:
                self.release_user(user_id)
                logger.debug(
                    "ActionLock preempted for user {} (is_nav={}, prev_is_nav={}, elapsed={:.1f}s)",
                    user_id,
                    is_nav,
                    prev_is_nav,
                    elapsed,
                )
            else:
                logger.debug("Занятый user {} — событие пропущено (elapsed={:.1f}s)", user_id, elapsed)
                if isinstance(event, CallbackQuery):
                    await self._reject_busy_callback(event)
                elif isinstance(event, Message):
                    await self._reject_busy_message(event)
                return None

        self._token_seq += 1
        my_token = self._token_seq
        self._processing.add(user_id)
        self._processing_since[user_id] = time.monotonic()
        self._processing_is_nav[user_id] = is_nav
        self._processing_token[user_id] = my_token
        try:
            return await handler(event, data)
        finally:
            if self._processing_token.get(user_id) == my_token:
                self.release_user(user_id)
"""Единая блокировка бота: ручная (отладка) и автоматическая (★ Primary недоступна)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.settings import settings
from db import bot_settings as bot_settings_db
from services.primary_gate import is_primary_operational
from ui.theme import screen

MAINTENANCE_ALERT = "Бот на техобслуживании. Попробуйте позже."
PRIMARY_UNAVAILABLE_ALERT = "Сервис временно недоступен. Попробуйте позже."
NEW_PAYMENT_BLOCKED_ALERT = "Новые оплаты временно недоступны."


def maintenance_message() -> str:
    return screen(
        "🔧 <b>Техническое обслуживание</b>",
        "Бот временно недоступен — проводим плановые работы.",
        hint="Попробуйте зайти позже. При срочном вопросе — напишите в поддержку.",
        footer="🙏 <i>Спасибо за понимание</i>",
    )


def primary_unavailable_message() -> str:
    return screen(
        "⚠️ <b>Сервис временно недоступен</b>",
        "Панель VPN сейчас на обслуживании — подключения могут не работать.",
        hint="Попробуйте позже или напишите в поддержку.",
    )


def new_payment_blocked_message() -> str:
    return screen(
        "⏳ <b>Оплата временно приостановлена</b>",
        "Идёт подготовка к техобслуживанию — новые тарифы и счета пока недоступны.",
        hint="Если у вас есть незавершённый платёж — вернитесь к нему из главного меню.",
    )

_was_draining: bool = False


@dataclass(frozen=True)
class LockdownStatus:
    manual: bool
    primary_ok: bool
    pending_orders: int = 0

    @property
    def draining(self) -> bool:
        return self.manual and self.pending_orders > 0

    @property
    def full_manual(self) -> bool:
        return self.manual and self.pending_orders == 0

    @property
    def active(self) -> bool:
        """Полная блокировка (middleware)."""
        return not self.primary_ok or self.full_manual

    @property
    def restricted(self) -> bool:
        return not self.primary_ok or self.manual

    @property
    def summary_label(self) -> str:
        if self.draining:
            return f"ожидание оплат ({self.pending_orders})"
        if self.manual and not self.primary_ok:
            return "ручная + ★ Primary"
        if self.manual:
            return "ручная"
        if not self.primary_ok:
            return "★ Primary недоступна"
        return "выкл"


async def get_lockdown_status() -> LockdownStatus:
    from db import database as db

    manual = await bot_settings_db.is_bot_lockdown_enabled()
    primary_ok = await is_primary_operational()
    pending_orders = await db.count_pending_orders() if manual else 0
    return LockdownStatus(
        manual=manual,
        primary_ok=primary_ok,
        pending_orders=pending_orders,
    )


async def is_lockdown_active() -> bool:
    return (await get_lockdown_status()).active


async def is_lockdown_enabled() -> bool:
    """Ручная блокировка из админки (не путать с is_lockdown_active)."""
    return await bot_settings_db.is_bot_lockdown_enabled()


async def set_lockdown_enabled(enabled: bool) -> None:
    global _was_draining
    await bot_settings_db.set_bot_lockdown_enabled(enabled)
    if not enabled:
        _was_draining = False


async def on_manual_lockdown_enabled() -> None:
    """Вызывается при включении ручной блокировки из админки."""
    global _was_draining
    from services.lockdown_alerts import (
        notify_admins_lockdown_draining,
        notify_admins_lockdown_full,
    )

    status = await get_lockdown_status()
    if status.draining:
        _was_draining = True
        await notify_admins_lockdown_draining(pending_count=status.pending_orders)
    else:
        _was_draining = False
        await notify_admins_lockdown_full(immediate=True)


async def sync_lockdown_drain_state() -> None:
    """После завершения PENDING: уведомить админов о полной блокировке."""
    global _was_draining
    if not await is_lockdown_enabled():
        _was_draining = False
        return

    status = await get_lockdown_status()
    if _was_draining and status.full_manual and status.primary_ok:
        from services.lockdown_alerts import notify_admins_lockdown_full

        _was_draining = False
        await notify_admins_lockdown_full(immediate=False)
    elif status.draining:
        _was_draining = True


async def get_whitelist() -> list[int]:
    return await bot_settings_db.get_bot_lockdown_whitelist()


async def add_to_whitelist(tg_id: int) -> list[int]:
    tg_id = int(tg_id)
    current = await get_whitelist()
    if tg_id not in current:
        current.append(tg_id)
    return await bot_settings_db.set_bot_lockdown_whitelist(current)


async def remove_from_whitelist(tg_id: int) -> list[int]:
    tg_id = int(tg_id)
    current = [x for x in await get_whitelist() if x != tg_id]
    return await bot_settings_db.set_bot_lockdown_whitelist(current)


async def _is_privileged_async(tg_id: int) -> bool:
    if tg_id in settings.BOT_ADMINS:
        return True
    return int(tg_id) in await get_whitelist()


async def is_user_allowed(tg_id: int) -> bool:
    status = await get_lockdown_status()
    if status.draining:
        return True
    if not status.active:
        return True
    return await _is_privileged_async(tg_id)


async def is_new_payment_allowed(tg_id: int) -> bool:
    if await _is_privileged_async(tg_id):
        return True
    status = await get_lockdown_status()
    return not status.manual


async def get_new_payment_block_response(tg_id: int) -> tuple[str, str] | None:
    """(alert, HTML-сообщение) или None."""
    if await is_new_payment_allowed(tg_id):
        return None
    return NEW_PAYMENT_BLOCKED_ALERT, new_payment_blocked_message()


async def get_block_response() -> tuple[str, str] | None:
    """
    Тексты отказа: (alert для callback, HTML-сообщение).
    None — полной блокировки нет.
    """
    status = await get_lockdown_status()
    if status.draining or not status.active:
        return None
    if status.manual:
        return MAINTENANCE_ALERT, maintenance_message()
    return PRIMARY_UNAVAILABLE_ALERT, primary_unavailable_message()


async def whitelist_users_info() -> list[dict[str, Any]]:
    from db import database as db

    rows: list[dict[str, Any]] = []
    for tg_id in await get_whitelist():
        user = await db.get_user(tg_id)
        rows.append({
            "tg_id": tg_id,
            "username": (user or {}).get("username"),
            "first_name": (user or {}).get("first_name"),
        })
    return rows
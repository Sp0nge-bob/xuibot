"""Уведомления админам о фазах блокировки бота."""
from __future__ import annotations

from loguru import logger

from config.settings import settings


async def _notify_admins(text: str) -> int:
    from bot.sender import send_message
    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Lockdown admin notify skipped — BOT_ADMINS empty")
        return 0
    sent = 0
    for admin_id in admin_ids:
        try:
            await send_message(admin_id, text)
            sent += 1
        except Exception as e:
            logger.error("Lockdown admin notify failed for admin {}: {}", admin_id, e)
    return sent


async def notify_admins_lockdown_draining(*, pending_count: int) -> int:
    text = (
        "🔒 <b>Блокировка: ожидание оплат</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Активных PENDING-заказов: <b>{pending_count}</b>\n\n"
        "Новые тарифы и оплаты заблокированы.\n"
        "Текущие незавершённые платежи можно довести до конца.\n\n"
        "Когда все PENDING завершатся — бот полностью заблокируется "
        "(кроме админов и белого списка)."
    )
    return await _notify_admins(text)


async def notify_admins_lockdown_full(*, immediate: bool = False) -> int:
    if immediate:
        lead = "Блокировка включена — активных PENDING-заказов нет."
    else:
        lead = "Все PENDING-заказы завершены."
    text = (
        "🔒 <b>Полная блокировка активна</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{lead}\n\n"
        "Бот недоступен всем, кроме админов и белого списка."
    )
    return await _notify_admins(text)
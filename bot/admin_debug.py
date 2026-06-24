"""Админские инструменты отладки."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from db import database as db
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db import tickets as tickets_db
from db import trial_grants as trial_db
from services.xui import remove_client_everywhere
from config.settings import settings
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_back_kb,
    admin_debug_entry_confirm_kb,
    admin_debug_kb,
    admin_debug_orders_reset_confirm_kb,
    admin_debug_promo_reset_confirm_kb,
    admin_debug_tickets_reset_confirm_kb,
    admin_debug_users_reset_confirm_kb,
)
from .messages import (
    admin_debug_entry_confirm_text,
    admin_debug_menu_text,
    admin_debug_orders_reset_confirm_text,
    admin_debug_promo_reset_confirm_text,
    admin_debug_tickets_reset_confirm_text,
    admin_debug_users_reset_confirm_text,
)
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _debug_allowed(user_id: int) -> bool:
    return is_admin(user_id) and settings.ALLOW_DEBUG_ADMIN


async def _show_debug_menu(cb: CallbackQuery) -> None:
    trial_count = await db.count_active_trial_subscriptions()
    promo_uses = await promo_db.count_promo_uses()
    promo_pending = await pending_db.count_pending_discounts()
    orders_count = await db.count_orders()
    tickets_count = await tickets_db.count_tickets()
    ticket_messages_count = await tickets_db.count_ticket_messages()
    users_count = await db.count_users()
    await send_or_edit(
        cb,
        admin_debug_menu_text(
            trial_count=trial_count,
            promo_uses=promo_uses,
            promo_pending=promo_pending,
            orders_count=orders_count,
            tickets_count=tickets_count,
            ticket_messages_count=ticket_messages_count,
            users_count=users_count,
        ),
        admin_debug_kb(),
    )


@router.callback_query(F.data == "adm:debug")
async def cb_admin_debug_entry(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_debug_entry_confirm_text(), admin_debug_entry_confirm_kb())


@router.callback_query(F.data == "adm:debug:enter")
async def cb_admin_debug_menu(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_debug_menu(cb)


@router.callback_query(F.data == "adm:debug:promos_reset")
async def cb_admin_debug_promos_reset_confirm(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    uses_count = await promo_db.count_promo_uses()
    pending_count = await pending_db.count_pending_discounts()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_promo_reset_confirm_text(
            uses_count=uses_count,
            pending_count=pending_count,
        ),
        admin_debug_promo_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:promos_reset:confirm")
async def cb_admin_debug_promos_reset(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Очищаем…")
    try:
        result = await promo_db.reset_all_promo_applications()
    except Exception as e:
        logger.exception("Promo reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Применения промокодов очищены</b>\n\n"
        f"Удалено promo_uses: <b>{result['uses_deleted']}</b>\n"
        f"Удалено pending: <b>{result['pending_deleted']}</b>\n"
        "Счётчики <code>used_count</code> обнулены."
    )
    await send_or_edit(cb, text, admin_debug_kb())


@router.callback_query(F.data == "adm:debug:orders_reset")
async def cb_admin_debug_orders_reset_confirm(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    orders_count = await db.count_orders()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_orders_reset_confirm_text(orders_count=orders_count),
        admin_debug_orders_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:orders_reset:confirm")
async def cb_admin_debug_orders_reset(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    try:
        result = await db.reset_all_orders()
    except Exception as e:
        logger.exception("Orders reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>История заказов очищена</b>\n\n"
        f"Удалено заказов: <b>{result['orders_deleted']}</b>\n"
        f"Тикетов отвязано от заказов: <b>{result['tickets_unlinked']}</b>"
    )
    await send_or_edit(cb, text, admin_debug_kb())


@router.callback_query(F.data == "adm:debug:tickets_reset")
async def cb_admin_debug_tickets_reset_confirm(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    tickets_count = await tickets_db.count_tickets()
    messages_count = await tickets_db.count_ticket_messages()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_tickets_reset_confirm_text(
            tickets_count=tickets_count,
            messages_count=messages_count,
        ),
        admin_debug_tickets_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:tickets_reset:confirm")
async def cb_admin_debug_tickets_reset(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    try:
        result = await tickets_db.reset_all_tickets()
    except Exception as e:
        logger.exception("Tickets reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Учёт тикетов очищен</b>\n\n"
        f"Удалено тикетов: <b>{result['tickets_deleted']}</b>\n"
        f"Удалено сообщений: <b>{result['messages_deleted']}</b>"
    )
    await send_or_edit(cb, text, admin_debug_kb())


@router.callback_query(F.data == "adm:debug:users_reset")
async def cb_admin_debug_users_reset_confirm(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    users_count = await db.count_users()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_users_reset_confirm_text(users_count=users_count),
        admin_debug_users_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:users_reset:confirm")
async def cb_admin_debug_users_reset(cb: CallbackQuery):
    if not _debug_allowed(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    await send_or_edit(cb, "⏳ Удаляем пользователей и подписки с панели…")
    panel_removed = 0
    panel_errors = 0
    try:
        subs = await db.get_all_active_subscriptions()
        for sub in subs:
            email = sub.get("client_email")
            if not email:
                continue
            try:
                await remove_client_everywhere(email)
                panel_removed += 1
            except Exception as e:
                panel_errors += 1
                logger.error(
                    "Users reset: panel remove failed for #{} ({}): {}",
                    sub.get("id"),
                    email,
                    e,
                )
        result = await db.reset_all_users()
        grants_deleted = await trial_db.reset_all_trial_grants()
    except Exception as e:
        logger.exception("Users reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Учёт пользователей очищен</b>\n\n"
        f"Удалено users: <b>{result['users_deleted']}</b>\n"
        f"Деактивировано подписок: <b>{result.get('subs_deactivated', 0)}</b>\n"
        f"С панели 3x-ui: <b>{panel_removed}</b>"
    )
    if panel_errors:
        text += f"\nОшибок на панели: <b>{panel_errors}</b>"
    if grants_deleted:
        text += f"\nСброшено пробных лимитов: <b>{grants_deleted}</b>"
    await send_or_edit(cb, text, admin_debug_kb())
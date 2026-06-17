"""Админские инструменты отладки."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from db import database as db
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_back_kb,
    admin_debug_entry_confirm_kb,
    admin_debug_kb,
    admin_debug_orders_reset_confirm_kb,
    admin_debug_promo_reset_confirm_kb,
)
from .messages import (
    admin_debug_entry_confirm_text,
    admin_debug_menu_text,
    admin_debug_orders_reset_confirm_text,
    admin_debug_promo_reset_confirm_text,
)
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_debug_menu(cb: CallbackQuery) -> None:
    trial_count = await db.count_active_trial_subscriptions()
    promo_uses = await promo_db.count_promo_uses()
    promo_pending = await pending_db.count_pending_discounts()
    orders_count = await db.count_orders()
    await send_or_edit(
        cb,
        admin_debug_menu_text(
            trial_count=trial_count,
            promo_uses=promo_uses,
            promo_pending=promo_pending,
            orders_count=orders_count,
        ),
        admin_debug_kb(),
    )


@router.callback_query(F.data == "adm:debug")
async def cb_admin_debug_entry(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_debug_entry_confirm_text(), admin_debug_entry_confirm_kb())


@router.callback_query(F.data == "adm:debug:enter")
async def cb_admin_debug_menu(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_debug_menu(cb)


@router.callback_query(F.data == "adm:debug:promos_reset")
async def cb_admin_debug_promos_reset_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
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
    if not is_admin(cb.from_user.id):
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
    if not is_admin(cb.from_user.id):
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
    if not is_admin(cb.from_user.id):
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
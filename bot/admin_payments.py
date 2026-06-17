"""Админка: включение и отключение способов оплаты."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from db import payment_methods as pay_methods_db
from .admin_auth import is_admin
from .admin_keyboards import admin_payment_methods_kb, admin_back_kb
from .messages import admin_payment_methods_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_payment_methods(cb: CallbackQuery) -> None:
    enabled = await pay_methods_db.get_payment_methods_enabled()
    await send_or_edit(
        cb,
        admin_payment_methods_text(enabled),
        admin_payment_methods_kb(enabled),
    )


@router.callback_query(F.data == "adm:payments")
async def cb_admin_payments(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_payment_methods(cb)


@router.callback_query(F.data.startswith("adm:payments:toggle:"))
async def cb_admin_payments_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    key = cb.data.split(":", 3)[3]
    try:
        await pay_methods_db.toggle_payment_method(key)
    except ValueError as e:
        await safe_cb_answer(cb, str(e), show_alert=True)
        return
    await safe_cb_answer(cb, "Сохранено")
    await _show_payment_methods(cb)
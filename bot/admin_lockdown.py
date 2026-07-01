"""Управление блокировкой бота (Отладка)."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.admin_auth import is_admin, is_debug_admin
from services.bot_lockdown import (
    add_to_whitelist,
    get_lockdown_status,
    get_whitelist,
    is_lockdown_enabled,
    on_manual_lockdown_enabled,
    remove_from_whitelist,
    set_lockdown_enabled,
    whitelist_users_info,
)
from .admin_keyboards import admin_debug_lockdown_kb
from .messages import admin_debug_lockdown_menu_text, admin_debug_lockdown_add_prompt_text
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_lockdown_menu(target: CallbackQuery | Message) -> None:
    status = await get_lockdown_status()
    users = await whitelist_users_info()
    text = admin_debug_lockdown_menu_text(
        manual_enabled=status.manual,
        primary_ok=status.primary_ok,
        pending_orders=status.pending_orders,
        draining=status.draining,
        whitelist=users,
    )
    kb = admin_debug_lockdown_kb(users, enabled=status.manual)
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:debug:lockdown")
async def cb_admin_lockdown_menu(cb: CallbackQuery, state: FSMContext):
    if not is_debug_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_lockdown_menu(cb)


@router.callback_query(F.data == "adm:debug:lockdown:toggle")
async def cb_admin_lockdown_toggle(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    current = await is_lockdown_enabled()
    enabling = not current
    await set_lockdown_enabled(enabling)
    if enabling:
        await on_manual_lockdown_enabled()
    label = "включена" if enabling else "снята"
    await safe_cb_answer(cb, f"Блокировка {label}")
    await _show_lockdown_menu(cb)


@router.callback_query(F.data == "adm:debug:lockdown:add")
async def cb_admin_lockdown_add(cb: CallbackQuery, state: FSMContext):
    if not is_debug_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_lockdown_whitelist)
    await safe_cb_answer(cb)
    status = await get_lockdown_status()
    await send_or_edit(cb, admin_debug_lockdown_add_prompt_text(), admin_debug_lockdown_kb(
        await whitelist_users_info(),
        enabled=status.manual,
        add_mode=True,
    ))


@router.message(AdminStates.waiting_lockdown_whitelist)
async def msg_admin_lockdown_add(message: Message, state: FSMContext):
    if not is_debug_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите числовой TG ID.")
        return

    tg_id = int(raw)
    if is_admin(tg_id):
        await message.answer("Этот пользователь уже админ — доступ есть без белого списка.")
        await state.set_state(None)
        await _show_lockdown_menu(message)
        return

    if tg_id in await get_whitelist():
        await message.answer("Пользователь уже в белом списке.")
        await state.set_state(None)
        await _show_lockdown_menu(message)
        return

    await add_to_whitelist(tg_id)
    await state.set_state(None)
    await message.answer(f"✅ TG ID <code>{tg_id}</code> добавлен в белый список.")
    await _show_lockdown_menu(message)


@router.callback_query(F.data.startswith("adm:debug:lockdown:remove:"))
async def cb_admin_lockdown_remove(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    tg_id = int(cb.data.split(":")[4])
    await remove_from_whitelist(tg_id)
    await safe_cb_answer(cb, "Удалён из белого списка")
    await _show_lockdown_menu(cb)
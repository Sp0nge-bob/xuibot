"""Админка: лимит одновременных подключений (limitIp) для trial и платных подписок."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import bot_settings as bot_settings_db
from services.limit_ip import apply_limit_ip_settings_on_primary
from .admin_auth import is_admin
from .admin_keyboards import admin_back_kb, admin_limit_ip_kb
from .messages import admin_limit_ip_edit_prompt_text, admin_limit_ip_text
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_limit_ip(target: CallbackQuery | Message) -> None:
    trial_limit = await bot_settings_db.get_trial_limit_ip()
    paid_limit = await bot_settings_db.get_paid_limit_ip()
    text = admin_limit_ip_text(trial_limit=trial_limit, paid_limit=paid_limit)
    kb = admin_limit_ip_kb()
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:limit_ip")
async def cb_admin_limit_ip(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_limit_ip(cb)


@router.callback_query(F.data.startswith("adm:limit_ip:edit:"))
async def cb_admin_limit_ip_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    kind = cb.data.split(":", 3)[3]
    if kind not in {"trial", "paid"}:
        await safe_cb_answer(cb, "Неизвестный тип", show_alert=True)
        return
    current = (
        await bot_settings_db.get_trial_limit_ip()
        if kind == "trial"
        else await bot_settings_db.get_paid_limit_ip()
    )
    await state.set_state(
        AdminStates.waiting_trial_limit_ip
        if kind == "trial"
        else AdminStates.waiting_paid_limit_ip,
    )
    await state.update_data(limit_ip_kind=kind)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_limit_ip_edit_prompt_text(kind=kind, current=current),
        admin_back_kb(),
    )


async def _handle_limit_ip_input(message: Message, state: FSMContext, *, kind: str) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ Введите целое число, например: 3")
        return
    value = int(raw)
    if kind == "trial":
        await bot_settings_db.set_trial_limit_ip(value)
    else:
        await bot_settings_db.set_paid_limit_ip(value)
    stats = await apply_limit_ip_settings_on_primary(kind=kind)
    await state.set_state(None)
    await message.answer(
        f"✅ Сохранено: <b>{value}</b>\n"
        f"Основная панель: обновлено <b>{stats['updated']}</b>, "
        f"без изменений <b>{stats['skipped']}</b>"
        + (f", нет на панели <b>{stats['missing']}</b>" if stats["missing"] else "")
        + (f", ошибок <b>{stats['failed']}</b>" if stats["failed"] else "")
        + "\n<i>Вторичные ноды подтянет сама панель 3x-ui.</i>",
    )
    trial_limit = await bot_settings_db.get_trial_limit_ip()
    paid_limit = await bot_settings_db.get_paid_limit_ip()
    await message.answer(
        admin_limit_ip_text(trial_limit=trial_limit, paid_limit=paid_limit),
        reply_markup=admin_limit_ip_kb(),
    )


@router.message(AdminStates.waiting_trial_limit_ip)
async def msg_trial_limit_ip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if data.get("limit_ip_kind") != "trial":
        await state.set_state(None)
        await message.answer("Сессия истекла. /admin")
        return
    if (message.text or "").strip().startswith("/"):
        await state.set_state(None)
        from bot.admin import _admin_menu_text, admin_menu_kb
        await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
        return
    await _handle_limit_ip_input(message, state, kind="trial")


@router.message(AdminStates.waiting_paid_limit_ip)
async def msg_paid_limit_ip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if data.get("limit_ip_kind") != "paid":
        await state.set_state(None)
        await message.answer("Сессия истекла. /admin")
        return
    if (message.text or "").strip().startswith("/"):
        await state.set_state(None)
        from bot.admin import _admin_menu_text, admin_menu_kb
        await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
        return
    await _handle_limit_ip_input(message, state, kind="paid")
"""Редактирование произвольного блока сообщения /start."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from db import bot_settings as settings_db
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_start_text_clear_confirm_kb,
    admin_start_text_kb,
)
from .messages import admin_start_text_edit_prompt_text, admin_start_text_menu_text
from .states import AdminStates
from .telegram_html import safe_html_fragment, validate_telegram_html
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_start_text_menu(target: CallbackQuery | Message) -> None:
    announcement = await settings_db.get_start_announcement()
    html_invalid = bool(announcement and validate_telegram_html(announcement))
    preview = safe_html_fragment(announcement) if announcement else None
    text = admin_start_text_menu_text(preview, html_invalid=html_invalid)
    kb = admin_start_text_kb(has_text=bool(announcement))
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:start_text")
async def cb_admin_start_text(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_start_text_menu(cb)


@router.callback_query(F.data == "adm:start_text:edit")
async def cb_admin_start_text_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_start_announcement)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_start_text_edit_prompt_text(), admin_start_text_kb(
        has_text=bool(await settings_db.get_start_announcement()),
    ))


@router.callback_query(F.data == "adm:start_text:clear")
async def cb_admin_start_text_clear_confirm(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🗑 <b>Очистить сообщение /start?</b>\n\n"
        "Блок новостей будет удалён. Системное меню останется без изменений.",
        admin_start_text_clear_confirm_kb(),
    )


@router.callback_query(F.data == "adm:start_text:clear:confirm")
async def cb_admin_start_text_clear(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await settings_db.clear_start_announcement()
    await safe_cb_answer(cb, "Сообщение очищено")
    await _show_start_text_menu(cb)


@router.message(AdminStates.waiting_start_announcement)
async def msg_admin_start_text_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    raw = message.text or ""
    if raw.strip().startswith("/"):
        cmd = raw.strip().split()[0].split("@")[0].lower()
        if cmd == "/admin":
            await state.set_state(None)
            from bot.admin import _admin_menu_text, admin_menu_kb
            await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
            return
        await message.answer("Ввод отменён.")
        await state.set_state(None)
        return

    body = raw.strip()
    if not body:
        await message.answer("❌ Отправьте непустой текст или /admin для отмены.")
        return

    if len(body) > 3500:
        await message.answer("❌ Слишком длинный текст (макс. 3500 символов).")
        return

    html_error = validate_telegram_html(body)
    if html_error:
        await message.answer(
            "❌ <b>Ошибка HTML</b>\n\n"
            f"{html_error}\n\n"
            "Исправьте разметку и отправьте снова. Каждый открытый тег "
            "(например, <code>&lt;b&gt;</code>) должен иметь парный "
            "<code>&lt;/b&gt;</code>."
        )
        return

    await settings_db.set_start_announcement(body)
    await state.set_state(None)
    await message.answer("✅ Сообщение /start сохранено.")
    await _show_start_text_menu(message)
"""Редактирование приветствия и блока новостей на экране /start."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from db import bot_settings as settings_db
from ui.theme import render_greeting
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_start_text_clear_confirm_kb,
    admin_start_text_kb,
)
from .messages import (
    admin_start_greeting_edit_prompt_text,
    admin_start_text_edit_prompt_text,
    admin_start_text_menu_text,
)
from .states import AdminStates
from .telegram_html import safe_html_fragment, validate_telegram_html
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_GREETING_MAX_LEN = 500
_ANNOUNCEMENT_MAX_LEN = 3500
_PREVIEW_NAME = "Алекс"
_PREVIEW_USERNAME = "alex"


async def _show_start_text_menu(target: CallbackQuery | Message) -> None:
    greeting_tpl = await settings_db.get_start_greeting()
    greeting_preview = render_greeting(
        greeting_tpl, _PREVIEW_NAME, _PREVIEW_USERNAME,
    )
    greeting_html_invalid = bool(greeting_tpl and validate_telegram_html(greeting_tpl))

    announcement = await settings_db.get_start_announcement()
    announcement_html_invalid = bool(announcement and validate_telegram_html(announcement))
    announcement_preview = safe_html_fragment(announcement) if announcement else None

    text = admin_start_text_menu_text(
        greeting_preview,
        announcement_preview,
        greeting_html_invalid=greeting_html_invalid,
        announcement_html_invalid=announcement_html_invalid,
        greeting_is_custom=bool(greeting_tpl),
    )
    kb = admin_start_text_kb(
        has_greeting=bool(greeting_tpl),
        has_announcement=bool(announcement),
    )
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _cancel_to_admin(message: Message, state: FSMContext) -> bool:
    raw = message.text or ""
    if not raw.strip().startswith("/"):
        return False
    cmd = raw.strip().split()[0].split("@")[0].lower()
    if cmd != "/admin":
        await message.answer("Ввод отменён.")
        await state.set_state(None)
        return True
    await state.set_state(None)
    from bot.admin import _admin_menu_text, admin_menu_kb
    await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
    return True


@router.callback_query(F.data == "adm:start_text")
async def cb_admin_start_text(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_start_text_menu(cb)


@router.callback_query(F.data == "adm:start_text:greeting:edit")
async def cb_admin_start_greeting_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_start_greeting)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_start_greeting_edit_prompt_text(),
        admin_start_text_kb(
            has_greeting=bool(await settings_db.get_start_greeting()),
            has_announcement=bool(await settings_db.get_start_announcement()),
        ),
    )


@router.callback_query(F.data == "adm:start_text:greeting:clear")
async def cb_admin_start_greeting_clear(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await settings_db.clear_start_greeting()
    await safe_cb_answer(cb, "Приветствие сброшено")
    await _show_start_text_menu(cb)


@router.callback_query(F.data == "adm:start_text:edit")
async def cb_admin_start_text_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_start_announcement)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_start_text_edit_prompt_text(),
        admin_start_text_kb(
            has_greeting=bool(await settings_db.get_start_greeting()),
            has_announcement=bool(await settings_db.get_start_announcement()),
        ),
    )


@router.callback_query(F.data == "adm:start_text:clear")
async def cb_admin_start_text_clear_confirm(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🗑 <b>Очистить блок новостей?</b>\n\n"
        "Текст акций будет удалён. Приветствие и системное меню останутся.",
        admin_start_text_clear_confirm_kb(),
    )


@router.callback_query(F.data == "adm:start_text:clear:confirm")
async def cb_admin_start_text_clear(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await settings_db.clear_start_announcement()
    await safe_cb_answer(cb, "Блок новостей очищен")
    await _show_start_text_menu(cb)


@router.message(AdminStates.waiting_start_greeting)
async def msg_admin_start_greeting_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return

    body = (message.text or "").strip()
    if not body:
        await message.answer("❌ Отправьте непустой текст или /admin для отмены.")
        return

    if len(body) > _GREETING_MAX_LEN:
        await message.answer(f"❌ Слишком длинный текст (макс. {_GREETING_MAX_LEN} символов).")
        return

    html_error = validate_telegram_html(body)
    if html_error:
        await message.answer(
            "❌ <b>Ошибка HTML</b>\n\n"
            f"{html_error}\n\n"
            "Исправьте разметку и отправьте снова."
        )
        return

    await settings_db.set_start_greeting(body)
    await state.set_state(None)
    await message.answer("✅ Приветствие сохранено.")
    await _show_start_text_menu(message)


@router.message(AdminStates.waiting_start_announcement)
async def msg_admin_start_text_save(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return

    body = (message.text or "").strip()
    if not body:
        await message.answer("❌ Отправьте непустой текст или /admin для отмены.")
        return

    if len(body) > _ANNOUNCEMENT_MAX_LEN:
        await message.answer(f"❌ Слишком длинный текст (макс. {_ANNOUNCEMENT_MAX_LEN} символов).")
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
    await message.answer("✅ Блок новостей сохранён.")
    await _show_start_text_menu(message)
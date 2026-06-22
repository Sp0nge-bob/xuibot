"""Админка: ссылки на политику конфиденциальности и пользовательское соглашение."""
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import bot_settings as settings_db
from .admin_auth import is_admin
from .admin_keyboards import admin_legal_kb
from .messages import admin_legal_edit_prompt_text, admin_legal_menu_text
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_MAX_URL_LEN = 512


def _is_valid_legal_url(url: str) -> bool:
    raw = (url or "").strip()
    if not raw or len(raw) > _MAX_URL_LEN:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def _custom_flags() -> tuple[bool, bool]:
    privacy_raw = await settings_db.get_setting(settings_db.SETTING_PRIVACY_POLICY_URL)
    terms_raw = await settings_db.get_setting(settings_db.SETTING_TERMS_OF_SERVICE_URL)
    return bool((privacy_raw or "").strip()), bool((terms_raw or "").strip())


async def _show_legal_menu(target: CallbackQuery | Message) -> None:
    privacy_url = await settings_db.get_privacy_policy_url()
    terms_url = await settings_db.get_terms_of_service_url()
    privacy_custom, terms_custom = await _custom_flags()
    text = admin_legal_menu_text(
        privacy_url=privacy_url,
        terms_url=terms_url,
        privacy_custom=privacy_custom,
        terms_custom=terms_custom,
    )
    kb = admin_legal_kb(
        privacy_custom=privacy_custom,
        terms_custom=terms_custom,
    )
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:legal")
async def cb_admin_legal(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_legal_menu(cb)


@router.callback_query(F.data == "adm:legal:edit:privacy")
async def cb_admin_legal_edit_privacy(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    current = await settings_db.get_privacy_policy_url()
    await state.set_state(AdminStates.waiting_privacy_policy_url)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_legal_edit_prompt_text(kind="privacy", current=current))


@router.callback_query(F.data == "adm:legal:edit:terms")
async def cb_admin_legal_edit_terms(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    current = await settings_db.get_terms_of_service_url()
    await state.set_state(AdminStates.waiting_terms_of_service_url)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_legal_edit_prompt_text(kind="terms", current=current))


@router.callback_query(F.data == "adm:legal:reset:privacy")
async def cb_admin_legal_reset_privacy(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await settings_db.clear_privacy_policy_url()
    await safe_cb_answer(cb, "Сброшено")
    await _show_legal_menu(cb)


@router.callback_query(F.data == "adm:legal:reset:terms")
async def cb_admin_legal_reset_terms(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await settings_db.clear_terms_of_service_url()
    await safe_cb_answer(cb, "Сброшено")
    await _show_legal_menu(cb)


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


@router.message(AdminStates.waiting_privacy_policy_url)
async def msg_admin_privacy_url(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    url = (message.text or "").strip()
    if not _is_valid_legal_url(url):
        await message.answer(
            "❌ Некорректная ссылка. Укажите URL вида "
            "<code>https://example.com/doc</code>"
        )
        return
    await settings_db.set_privacy_policy_url(url)
    await state.set_state(None)
    await message.answer("✅ Ссылка на политику конфиденциальности сохранена.")
    await _show_legal_menu(message)


@router.message(AdminStates.waiting_terms_of_service_url)
async def msg_admin_terms_url(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    url = (message.text or "").strip()
    if not _is_valid_legal_url(url):
        await message.answer(
            "❌ Некорректная ссылка. Укажите URL вида "
            "<code>https://example.com/doc</code>"
        )
        return
    await settings_db.set_terms_of_service_url(url)
    await state.set_state(None)
    await message.answer("✅ Ссылка на пользовательское соглашение сохранена.")
    await _show_legal_menu(message)
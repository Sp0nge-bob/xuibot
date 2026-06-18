"""Админка: режим шифрования ссылок Happ."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config.happ_crypto import HAPP_CRYPTO_MODES, HAPP_CRYPTO_MODE_LABELS
from db import bot_settings as bot_settings_db
from services.happ_crypto import clear_happ_crypto_cache, get_happ_crypto_mode
from .admin_auth import is_admin
from .admin_keyboards import admin_happ_crypto_kb, admin_back_kb
from .messages import admin_happ_crypto_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_happ_crypto(cb: CallbackQuery) -> None:
    mode = await get_happ_crypto_mode()
    await send_or_edit(
        cb,
        admin_happ_crypto_text(mode),
        admin_happ_crypto_kb(mode),
    )


@router.callback_query(F.data == "adm:happ_crypto")
async def cb_admin_happ_crypto(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_happ_crypto(cb)


@router.callback_query(F.data.startswith("adm:happ_crypto:set:"))
async def cb_admin_happ_crypto_set(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    mode = cb.data.split(":", 3)[3]
    if mode not in HAPP_CRYPTO_MODES:
        await safe_cb_answer(cb, "Неизвестный режим", show_alert=True)
        return
    try:
        await bot_settings_db.set_happ_crypto_mode(mode)
    except ValueError as e:
        await safe_cb_answer(cb, str(e), show_alert=True)
        return
    clear_happ_crypto_cache()
    label = HAPP_CRYPTO_MODE_LABELS.get(mode, mode)
    await safe_cb_answer(cb, f"Режим: {label}")
    await _show_happ_crypto(cb)
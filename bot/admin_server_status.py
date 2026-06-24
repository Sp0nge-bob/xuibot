"""Админка: доступность инбаундов подписки для /start."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from db import bot_settings as bot_settings_db
from services.server_status import (
    format_admin_server_status_text,
    list_subscription_inbounds_status,
)
from .admin_auth import is_admin
from .admin_keyboards import admin_server_status_kb
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_admin_server_status(cb: CallbackQuery) -> None:
    items = await list_subscription_inbounds_status()
    await send_or_edit(
        cb,
        format_admin_server_status_text(items),
        admin_server_status_kb(items),
    )


@router.callback_query(F.data == "adm:server_status")
async def cb_admin_server_status(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_admin_server_status(cb)


@router.callback_query(F.data.startswith("adm:server_status:toggle:"))
async def cb_admin_server_status_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    try:
        inbound_id = int(cb.data.split(":")[3])
    except (IndexError, ValueError):
        await safe_cb_answer(cb, "Некорректные данные", show_alert=True)
        return

    allowed = await bot_settings_db.get_subscription_inbound_ids()
    if inbound_id not in allowed:
        await safe_cb_answer(cb, "Инбаунд не в подписке бота", show_alert=True)
        return

    try:
        new_val = await bot_settings_db.toggle_inbound_public_available(inbound_id)
    except Exception as e:
        logger.exception("Toggle inbound public status failed for #{}: {}", inbound_id, e)
        await safe_cb_answer(cb, f"Ошибка: {str(e)[:80]}", show_alert=True)
        return

    items = await list_subscription_inbounds_status()
    label = next((i.get("remark") for i in items if i.get("id") == inbound_id), f"#{inbound_id}")
    status = "работает" if new_val else "недоступен"
    await safe_cb_answer(cb, f"{label}: {status}")
    await _show_admin_server_status(cb)
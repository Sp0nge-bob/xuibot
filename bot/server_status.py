"""Экран «Доступность серверов» (инбаунды подписки) для пользователей."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from services.server_status import format_user_server_status_text, list_subscription_inbounds_status
from .keyboards import server_status_kb
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_server_status(cb: CallbackQuery) -> None:
    items = await list_subscription_inbounds_status()
    await send_or_edit(
        cb,
        format_user_server_status_text(items),
        server_status_kb(),
    )


@router.callback_query(F.data == "server_status")
async def cb_server_status(cb: CallbackQuery):
    await safe_cb_answer(cb)
    await _show_server_status(cb)
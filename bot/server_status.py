"""Экран «Доступность серверов» для пользователей."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from db import xui_nodes as nodes_db
from services.server_status import format_user_server_status_text
from .keyboards import server_status_kb
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_server_status(cb: CallbackQuery) -> None:
    nodes = await nodes_db.list_public_status_nodes()
    await send_or_edit(
        cb,
        format_user_server_status_text(nodes),
        server_status_kb(),
    )


@router.callback_query(F.data == "server_status")
async def cb_server_status(cb: CallbackQuery):
    await safe_cb_answer(cb)
    await _show_server_status(cb)
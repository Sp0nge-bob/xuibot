"""Админка: публичная доступность серверов для /start."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from db import xui_nodes as nodes_db
from services.server_status import format_admin_server_status_text
from .admin_auth import is_admin
from .admin_keyboards import admin_server_status_kb
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_admin_server_status(cb: CallbackQuery) -> None:
    nodes = await nodes_db.list_public_status_nodes()
    await send_or_edit(
        cb,
        format_admin_server_status_text(nodes),
        admin_server_status_kb(nodes),
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
        node_id = int(cb.data.split(":")[3])
    except (IndexError, ValueError):
        await safe_cb_answer(cb, "Некорректные данные", show_alert=True)
        return

    node = await nodes_db.get_node(node_id)
    if not node or not node.get("is_enabled"):
        await safe_cb_answer(cb, "Нода не найдена", show_alert=True)
        return

    try:
        new_val = await nodes_db.toggle_public_available(node_id)
    except Exception as e:
        logger.exception("Toggle public_available failed for node {}: {}", node_id, e)
        await safe_cb_answer(cb, f"Ошибка: {str(e)[:80]}", show_alert=True)
        return

    label = "работает" if new_val else "недоступен"
    await safe_cb_answer(cb, f"{node.get('name')}: {label}")
    await _show_admin_server_status(cb)
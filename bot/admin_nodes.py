"""Админка: управление нодами 3x-ui."""
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from db import xui_nodes as nodes_db
from services.node_health import check_all_nodes_health, check_node_health
from services.node_sync import sync_all_secondary_nodes
from services.xui import normalize_xui_host
from .admin_auth import is_admin
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _health_icon(node: dict) -> str:
    if not node.get("is_enabled"):
        return "⚪"
    return "🟢" if node.get("is_healthy") else "🔴"


def _short_host(host: str, max_len: int = 36) -> str:
    h = normalize_xui_host(host or "")
    if len(h) > max_len:
        return h[: max_len - 3] + "..."
    return h


async def _uptime_str(node_id: int) -> str:
    pct = await nodes_db.get_uptime_24h(node_id)
    if pct is None:
        return "—"
    return f"{int(pct * 100)}%"


async def nodes_list_text() -> str:
    nodes = await nodes_db.list_nodes()
    summary = await nodes_db.nodes_summary()
    lines = [
        "🖧 <b>Ноды 3x-ui</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Всего: <b>{summary['total']}</b> · healthy: <b>{summary['healthy']}</b>"
        f" / <b>{summary['enabled']}</b>",
        f"Основная: <b>{summary.get('primary', 0)}</b> · вторичные: <b>{summary.get('secondary', 0)}</b>",
        "",
    ]
    if not nodes:
        lines.append("Нод не настроено. Добавьте основную и вторичные.")
    else:
        lines.append("Краткий список (подробности — по кнопке ноды):")
        for n in nodes[:30]:
            primary = " ★" if n.get("is_primary") else ""
            uptime = await _uptime_str(n["id"])
            status = _health_icon(n)
            lines.append(
                f"{status} <b>{n['name']}</b>{primary} · {uptime} · "
                f"<code>{_short_host(n['host'], 28)}</code>"
            )
        if len(nodes) > 30:
            lines.append(f"… и ещё <b>{len(nodes) - 30}</b> (см. кнопки ниже)")
    return "\n".join(lines)


def nodes_list_kb(nodes: list) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(text="➕ Добавить ноду", callback_data="adm:node:add")]]
    for n in nodes:
        icon = _health_icon(n)
        primary = "★ " if n.get("is_primary") else ""
        rows.append([InlineKeyboardButton(
            text=f"{icon} {primary}{n['name']}",
            callback_data=f"adm:node:{n['id']}",
        )])
    rows += [
        [InlineKeyboardButton(text="🔄 Синхронизировать вторичные", callback_data="adm:nodes:sync")],
        [InlineKeyboardButton(text="🩺 Проверить все ноды", callback_data="adm:nodes:health")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def node_detail_kb(node: dict) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    nid = node["id"]
    rows = [
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"adm:node:edit:{nid}")],
        [InlineKeyboardButton(text="🩺 Проверить", callback_data=f"adm:node:health:{nid}")],
    ]
    if not node.get("is_primary"):
        rows.append([InlineKeyboardButton(
            text="★ Сделать основной",
            callback_data=f"adm:node:primary:{nid}",
        )])
    rows.append([InlineKeyboardButton(
        text="🗑 Удалить",
        callback_data=f"adm:node:del:{nid}",
    )])
    rows.append([InlineKeyboardButton(text="« К списку", callback_data="adm:nodes")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def node_detail_text(node: dict) -> str:
    uptime = await _uptime_str(node["id"])
    checked = (node.get("last_health_check_at") or "—")[:19]
    synced = (node.get("last_sync_at") or "—")[:19]
    err = node.get("last_health_error") or node.get("last_sync_error") or "—"
    return (
        f"🖧 <b>{node['name']}</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Роль: {'★ Основная' if node.get('is_primary') else 'Вторичная'}\n"
        f"Статус: {_health_icon(node)} "
        f"{'online' if node.get('is_healthy') else 'offline'}\n"
        f"Host: <code>{_short_host(node['host'], 64)}</code>\n"
        f"Inbounds: <code>{node.get('inbound_ids') or '—'}</code>\n"
        f"Enabled: {'да' if node.get('is_enabled') else 'нет'}\n\n"
        f"Uptime 24h: <b>{uptime}</b>\n"
        f"Latency: <b>{node.get('health_latency_ms') or '—'}</b> ms\n"
        f"Последняя проверка: {checked}\n"
        f"Последний синк: {synced}\n"
        f"Ошибка: <code>{str(err)[:200]}</code>"
    )


@router.callback_query(F.data == "adm:nodes")
async def cb_nodes_list(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    nodes = await nodes_db.list_nodes()
    await safe_cb_answer(cb)
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))


@router.callback_query(F.data == "adm:inbounds")
async def cb_inbounds_redirect(cb: CallbackQuery, state: FSMContext):
    await cb_nodes_list(cb, state)


@router.callback_query(F.data.regexp(r"^adm:node:\d+$"))
async def cb_node_detail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    node_id = int(cb.data.split(":")[2])
    node = await nodes_db.get_node(node_id)
    if not node:
        await safe_cb_answer(cb, "Нода не найдена", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(cb, await node_detail_text(node), node_detail_kb(node))


@router.callback_query(F.data == "adm:node:add")
async def cb_node_add(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_node_name)
    await state.update_data(node_edit_id=None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "➕ <b>Новая нода</b>\n\nВведите название (например NL, US):",
    )


@router.callback_query(F.data.startswith("adm:node:edit:"))
async def cb_node_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    node_id = int(cb.data.split(":")[3])
    node = await nodes_db.get_node(node_id)
    if not node:
        await safe_cb_answer(cb, "Не найдена", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_node_name)
    await state.update_data(node_edit_id=node_id, node_draft=dict(node))
    await safe_cb_answer(cb)
    await send_or_edit(cb, f"✏️ Редактирование <b>{node['name']}</b>\n\nНовое название:")


@router.message(AdminStates.waiting_node_name)
async def msg_node_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название.")
        return
    data = await state.get_data()
    draft = data.get("node_draft") or {}
    draft["name"] = name
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_host)
    await message.answer(f"Host панели 3x-ui для <b>{name}</b>:\n(HTTPS URL без /panel)")


@router.message(AdminStates.waiting_node_host)
async def msg_node_host(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    host = (message.text or "").strip()
    if not host.startswith("http"):
        await message.answer("Укажите полный URL, например https://node.example.com/secret")
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["host"] = host
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_token)
    await message.answer(
        "API token (или <code>-</code> для login/password):",
        parse_mode="HTML",
    )


@router.message(AdminStates.waiting_node_token)
async def msg_node_token(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    draft = (await state.get_data()).get("node_draft") or {}
    if raw == "-":
        draft["token"] = ""
        await state.update_data(node_draft=draft)
        await state.set_state(AdminStates.waiting_node_login)
        await message.answer("Username панели:")
        return
    draft["token"] = raw
    draft["username"] = ""
    draft["password"] = ""
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_inbounds)
    await message.answer("ID инбаундов через запятую (на этой панели):")


@router.message(AdminStates.waiting_node_login)
async def msg_node_login(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["username"] = (message.text or "").strip()
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_password)
    await message.answer("Password:")


@router.message(AdminStates.waiting_node_password)
async def msg_node_password(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["password"] = message.text or ""
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_inbounds)
    await message.answer("ID инбаундов через запятую:")


@router.message(AdminStates.waiting_node_inbounds)
async def msg_node_inbounds(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not re.fullmatch(r"[\d,\s]+", raw):
        await message.answer("Формат: 1,16")
        return
    ids = nodes_db.parse_inbound_ids(raw)
    if not ids:
        await message.answer("Укажите хотя бы один inbound ID.")
        return

    data = await state.get_data()
    draft = data.get("node_draft") or {}
    edit_id = data.get("node_edit_id")

    if edit_id:
        await nodes_db.update_node(
            edit_id,
            name=draft.get("name"),
            host=draft.get("host"),
            username=draft.get("username", ""),
            password=draft.get("password", ""),
            token=draft.get("token", ""),
            inbound_ids=ids,
        )
        node = await nodes_db.get_node(edit_id)
        await state.clear()
        await message.answer("✅ Нода обновлена.", reply_markup=node_detail_kb(node))
        return

    count = await nodes_db.count_nodes()
    is_primary = count == 0
    node_id = await nodes_db.create_node(
        name=draft["name"],
        host=draft["host"],
        username=draft.get("username", ""),
        password=draft.get("password", ""),
        token=draft.get("token", ""),
        inbound_ids=ids,
        is_primary=is_primary,
    )
    await state.clear()
    node = await nodes_db.get_node(node_id)
    await message.answer(
        f"✅ Нода <b>{node['name']}</b> добавлена"
        + (" как основная." if is_primary else "."),
        reply_markup=node_detail_kb(node),
    )


@router.callback_query(F.data.startswith("adm:node:health:"))
async def cb_node_health(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    node_id = int(cb.data.split(":")[3])
    node = await nodes_db.get_node(node_id)
    if not node:
        await safe_cb_answer(cb, "Не найдена", show_alert=True)
        return
    await safe_cb_answer(cb, "Проверяем…")
    result = await check_node_health(node)
    node = await nodes_db.get_node(node_id)
    status = "online" if result.get("ok") else "offline"
    await send_or_edit(
        cb,
        await node_detail_text(node) + f"\n\n🩺 Проверка: <b>{status}</b>",
        node_detail_kb(node),
    )


@router.callback_query(F.data == "adm:nodes:health")
async def cb_nodes_health_all(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb, "Проверяем все ноды…")
    await check_all_nodes_health()
    nodes = await nodes_db.list_nodes()
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))


@router.callback_query(F.data == "adm:nodes:sync")
async def cb_nodes_sync(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb, "Синхронизация…")
    await send_or_edit(cb, "⏳ Синхронизация вторичных нод…")
    try:
        stats = await sync_all_secondary_nodes()
        text = (
            "✅ <b>Синхронизация завершена</b>\n\n"
            f"Подписок: {stats['subs']}\n"
            f"Нод: {stats['nodes']}\n"
            f"Успешно: {stats['ok']}\n"
            f"Ошибок: {stats['failed']}"
        )
    except Exception as e:
        logger.exception("Manual sync failed: {}", e)
        text = f"❌ Ошибка синхронизации: <code>{str(e)[:120]}</code>"
    nodes = await nodes_db.list_nodes()
    await send_or_edit(cb, text, nodes_list_kb(nodes))


@router.callback_query(F.data.startswith("adm:node:primary:"))
async def cb_node_set_primary(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    node_id = int(cb.data.split(":")[3])
    ok = await nodes_db.set_primary_node(node_id)
    await safe_cb_answer(cb, "Основная нода обновлена" if ok else "Ошибка")
    nodes = await nodes_db.list_nodes()
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))


@router.callback_query(F.data.startswith("adm:node:del:"))
async def cb_node_delete(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    node_id = int(cb.data.split(":")[3])
    ok, msg = await nodes_db.delete_node(node_id)
    if not ok:
        await safe_cb_answer(cb, msg, show_alert=True)
        return
    await safe_cb_answer(cb, "Удалено")
    nodes = await nodes_db.list_nodes()
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))
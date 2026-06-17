"""Админка: управление нодами 3x-ui."""
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from db import xui_nodes as nodes_db
from db.bot_settings import (
    get_subscription_inbounds_display,
    set_subscription_inbound_ids,
)
from services.node_health import check_all_nodes_health, check_node_health
from services.node_sync import sync_all_secondary_nodes
from services.xui import invalidate_api_cache, normalize_xui_host
from .admin_auth import is_admin
from .admin_keyboards import admin_inbounds_kb
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
        f"Уникальных панелей: <b>{summary.get('unique_hosts', summary['total'])}</b>",
        "",
    ]
    dupes = summary["total"] - summary.get("unique_hosts", summary["total"])
    if dupes > 0:
        lines.append(f"⚠️ Дубликатов в БД: <b>{dupes}</b> — нажмите «Очистить дубликаты»")
        lines.append("")
    lines.append(
        "<i>★ Основная — создание клиентов и инбаунды подписки.\n"
        "Вторичные — синк срока, трафика, enable и удаление.</i>"
    )
    lines.append("")
    if not nodes:
        lines.append("Нод не настроено. Сначала добавьте основную.")
    else:
        lines.append("Краткий список (подробности — по кнопке ноды):")
        for n in nodes[:15]:
            primary = " ★" if n.get("is_primary") else ""
            uptime = await _uptime_str(n["id"])
            status = _health_icon(n)
            lines.append(
                f"{status} <b>{n['name']}</b>{primary} · {uptime} · "
                f"<code>{_short_host(n['host'], 28)}</code>"
            )
        if len(nodes) > 15:
            lines.append(f"… и ещё <b>{len(nodes) - 15}</b> записей в БД")
    return "\n".join(lines)


_NODES_KB_LIMIT = 12


def nodes_list_kb(nodes: list) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [[InlineKeyboardButton(text="➕ Добавить ноду", callback_data="adm:node:add")]]
    shown = 0
    seen_hosts: set[str] = set()
    for n in nodes:
        if shown >= _NODES_KB_LIMIT:
            break
        host_key = nodes_db.normalize_node_host(n.get("host") or "")
        if host_key in seen_hosts:
            continue
        seen_hosts.add(host_key)
        icon = _health_icon(n)
        primary = "★ " if n.get("is_primary") else ""
        rows.append([InlineKeyboardButton(
            text=f"{icon} {primary}{n['name']}",
            callback_data=f"adm:node:{n['id']}",
        )])
        shown += 1
    unique_hosts = len({nodes_db.normalize_node_host(n.get("host") or "") for n in nodes if n.get("host")})
    dupes = len(nodes) - unique_hosts
    if dupes > 0:
        rows.append([InlineKeyboardButton(
            text=f"🧹 Очистить дубликаты ({dupes})",
            callback_data="adm:nodes:dedupe",
        )])
    rows += [
        [InlineKeyboardButton(text="🔄 Синхронизировать вторичные", callback_data="adm:nodes:sync")],
        [InlineKeyboardButton(text="🩺 Проверить все ноды", callback_data="adm:nodes:health")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def node_wizard_cancel_kb() -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:node:cancel")],
    ])


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
    is_primary = bool(node.get("is_primary"))
    role_hint = (
        "Создание клиентов, продление, ссылка подписки"
        if is_primary
        else "Синхронизация expiry / трафика / enable / удаление"
    )
    lines = [
        f"🖧 <b>{node['name']}</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Роль: {'★ Основная' if is_primary else 'Вторичная'}",
        f"<i>{role_hint}</i>",
        f"Статус: {_health_icon(node)} "
        f"{'online' if node.get('is_healthy') else 'offline'}",
        f"Host: <code>{_short_host(node['host'], 64)}</code>",
    ]
    if is_primary:
        lines.append(f"Inbounds подписки: <code>{node.get('inbound_ids') or '—'}</code>")
    lines += [
        f"Enabled: {'да' if node.get('is_enabled') else 'нет'}",
        "",
        f"Uptime 24h: <b>{uptime}</b>",
        f"Latency: <b>{node.get('health_latency_ms') or '—'}</b> ms",
        f"Последняя проверка: {checked}",
        f"Последний синк: {synced}",
        f"Ошибка: <code>{str(err)[:200]}</code>",
    ]
    return "\n".join(lines)


async def inbounds_page_text() -> str:
    current = await get_subscription_inbounds_display()
    primary = await nodes_db.get_primary_node()
    primary_name = (primary or {}).get("name") or "—"
    lines = [
        "📡 <b>Inbounds подписки</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Текущие ID: <code>{current or '—'}</code>",
        f"★ Основная нода: <b>{primary_name}</b>",
        "",
        "<i>Используются при создании новых клиентов на основной панели.</i>",
        "<i>На вторичные ноды уходят через синхронизацию панели.</i>",
        "",
        "Изменение не перепривязывает уже созданных клиентов —",
        "при необходимости запустите «Синхронизация нод».",
    ]
    if not primary or not (primary.get("id") or 0):
        lines += [
            "",
            "⚠️ Основная нода не настроена в БД — сначала добавьте ★ основную.",
        ]
    return "\n".join(lines)


async def _apply_subscription_inbounds(inbound_ids: list[int]) -> None:
    await set_subscription_inbound_ids(inbound_ids)
    primary = await nodes_db.get_primary_node()
    node_id = int((primary or {}).get("id") or 0)
    if node_id > 0:
        await nodes_db.update_node(node_id, inbound_ids=inbound_ids)


async def _node_will_be_primary(data: dict) -> bool:
    edit_id = data.get("node_edit_id")
    if edit_id:
        node = await nodes_db.get_node(edit_id)
        return bool(node and node.get("is_primary"))
    return await nodes_db.count_nodes() == 0


async def _save_node_from_draft(
    message: Message,
    state: FSMContext,
    *,
    inbound_ids: list[int],
) -> None:
    data = await state.get_data()
    draft = data.get("node_draft") or {}
    edit_id = data.get("node_edit_id")

    if edit_id:
        node_before = await nodes_db.get_node(edit_id)
        await nodes_db.update_node(
            edit_id,
            name=draft.get("name"),
            host=draft.get("host"),
            username=draft.get("username", ""),
            password=draft.get("password", ""),
            token=draft.get("token", ""),
            inbound_ids=inbound_ids if (node_before or {}).get("is_primary") else [],
        )
        if (node_before or {}).get("is_primary") and inbound_ids:
            await set_subscription_inbound_ids(inbound_ids)
        invalidate_api_cache(edit_id)
        node = await nodes_db.get_node(edit_id)
        await state.clear()
        await message.answer("✅ Нода обновлена.", reply_markup=node_detail_kb(node))
        return

    count = await nodes_db.count_nodes()
    is_primary = count == 0
    try:
        node_id = await nodes_db.create_node(
            name=draft["name"],
            host=draft["host"],
            username=draft.get("username", ""),
            password=draft.get("password", ""),
            token=draft.get("token", ""),
            inbound_ids=inbound_ids if is_primary else [],
            is_primary=is_primary,
        )
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    if is_primary and inbound_ids:
        await set_subscription_inbound_ids(inbound_ids)
    await state.clear()
    node = await nodes_db.get_node(node_id)
    await message.answer(
        f"✅ Нода <b>{node['name']}</b> добавлена"
        + (" как ★ основная." if is_primary else " как вторичная."),
        reply_markup=node_detail_kb(node),
    )


async def _proceed_after_node_auth(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if await _node_will_be_primary(data):
        await state.set_state(AdminStates.waiting_node_inbounds)
        await message.answer(
            "ID инбаундов подписки через запятую\n"
            "(только ★ основная; на ноды уйдёт через панель):\n"
            "Пример: <code>1,16</code>",
            parse_mode="HTML",
            reply_markup=node_wizard_cancel_kb(),
        )
        return
    await _save_node_from_draft(message, state, inbound_ids=[])


@router.callback_query(F.data == "adm:nodes")
async def cb_nodes_list(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    nodes = await nodes_db.list_nodes()
    await safe_cb_answer(cb)
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))


@router.callback_query(F.data == "adm:inbounds")
async def cb_inbounds_page(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    await send_or_edit(cb, await inbounds_page_text(), admin_inbounds_kb())


@router.callback_query(F.data == "adm:inbounds:edit")
async def cb_inbounds_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    primary = await nodes_db.get_primary_node()
    if not primary or not int((primary.get("id") or 0)):
        await safe_cb_answer(cb, "Сначала добавьте ★ основную ноду", show_alert=True)
        return
    current = await get_subscription_inbounds_display()
    await state.set_state(AdminStates.waiting_inbounds)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "✏️ <b>Inbounds подписки</b>\n\n"
        f"Сейчас: <code>{current or '—'}</code>\n\n"
        "Введите новые ID через запятую.\n"
        "Пример: <code>1,16</code>",
        node_wizard_cancel_kb(),
    )


@router.message(AdminStates.waiting_inbounds)
async def msg_inbounds_edit(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not re.fullmatch(r"[\d,\s]+", raw):
        await message.answer(
            "Формат: 1,16",
            reply_markup=node_wizard_cancel_kb(),
        )
        return
    ids = nodes_db.parse_inbound_ids(raw)
    if not ids:
        await message.answer(
            "Укажите хотя бы один inbound ID.",
            reply_markup=node_wizard_cancel_kb(),
        )
        return
    try:
        await _apply_subscription_inbounds(ids)
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=node_wizard_cancel_kb())
        return
    await state.clear()
    value = ", ".join(str(x) for x in ids)
    await message.answer(
        f"✅ Inbounds обновлены: <code>{value}</code>",
        reply_markup=admin_inbounds_kb(),
    )


@router.callback_query(F.data == "adm:node:cancel")
async def cb_node_wizard_cancel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    data = await state.get_data()
    edit_id = data.get("node_edit_id")
    inbound_edit = await state.get_state() == AdminStates.waiting_inbounds.state
    await state.clear()
    await safe_cb_answer(cb, "Отменено")
    if inbound_edit:
        await send_or_edit(cb, await inbounds_page_text(), admin_inbounds_kb())
        return
    if edit_id:
        node = await nodes_db.get_node(edit_id)
        if node:
            await send_or_edit(cb, await node_detail_text(node), node_detail_kb(node))
            return
    nodes = await nodes_db.list_nodes()
    await send_or_edit(cb, await nodes_list_text(), nodes_list_kb(nodes))


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
        "➕ <b>Новая нода</b>\n\n"
        "Первая нода станет ★ основной (с инбаундами подписки).\n"
        "Остальные — вторичные (только синк и удаление).\n\n"
        "Название (например NL, US):",
        node_wizard_cancel_kb(),
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
    await send_or_edit(
        cb,
        f"✏️ Редактирование <b>{node['name']}</b>\n\nНовое название:",
        node_wizard_cancel_kb(),
    )


@router.message(AdminStates.waiting_node_name)
async def msg_node_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if not name:
        await message.answer("Введите название.", reply_markup=node_wizard_cancel_kb())
        return
    data = await state.get_data()
    draft = data.get("node_draft") or {}
    draft["name"] = name
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_host)
    await message.answer(
        f"Host панели 3x-ui для <b>{name}</b>:\n(HTTPS URL без /panel)",
        reply_markup=node_wizard_cancel_kb(),
    )


@router.message(AdminStates.waiting_node_host)
async def msg_node_host(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    host = (message.text or "").strip()
    if not host.startswith("http"):
        await message.answer(
            "Укажите полный URL, например https://node.example.com/secret",
            reply_markup=node_wizard_cancel_kb(),
        )
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["host"] = host
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_token)
    await message.answer(
        "API token (или <code>-</code> для login/password):",
        parse_mode="HTML",
        reply_markup=node_wizard_cancel_kb(),
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
        await message.answer("Username панели:", reply_markup=node_wizard_cancel_kb())
        return
    draft["token"] = raw
    draft["username"] = ""
    draft["password"] = ""
    await state.update_data(node_draft=draft)
    await _proceed_after_node_auth(message, state)


@router.message(AdminStates.waiting_node_login)
async def msg_node_login(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["username"] = (message.text or "").strip()
    await state.update_data(node_draft=draft)
    await state.set_state(AdminStates.waiting_node_password)
    await message.answer("Password:", reply_markup=node_wizard_cancel_kb())


@router.message(AdminStates.waiting_node_password)
async def msg_node_password(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    draft = (await state.get_data()).get("node_draft") or {}
    draft["password"] = message.text or ""
    await state.update_data(node_draft=draft)
    await _proceed_after_node_auth(message, state)


@router.message(AdminStates.waiting_node_inbounds)
async def msg_node_inbounds(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not re.fullmatch(r"[\d,\s]+", raw):
        await message.answer("Формат: 1,16", reply_markup=node_wizard_cancel_kb())
        return
    ids = nodes_db.parse_inbound_ids(raw)
    if not ids:
        await message.answer(
            "Укажите хотя бы один inbound ID.",
            reply_markup=node_wizard_cancel_kb(),
        )
        return

    await _save_node_from_draft(message, state, inbound_ids=ids)


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


@router.callback_query(F.data == "adm:nodes:dedupe")
async def cb_nodes_dedupe(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb, "Очищаем дубликаты…")
    stats = await nodes_db.dedupe_nodes()
    nodes = await nodes_db.list_nodes()
    text = (
        "🧹 <b>Дубликаты очищены</b>\n\n"
        f"Было записей: <b>{stats['before']}</b>\n"
        f"Удалено: <b>{stats['removed']}</b>\n"
        f"Осталось: <b>{stats['after']}</b>"
    )
    await send_or_edit(cb, text, nodes_list_kb(nodes))


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
            f"Подписок в БД: {stats['subs']}\n"
            f"Основная: создано {stats.get('primary_created', 0)}, "
            f"обновлено {stats.get('primary_updated', 0)}, "
            f"лишних удалено {stats.get('primary_orphans_purged', 0)}\n"
            f"Вторичные: нод {stats['nodes']}, expiry обновлено {stats['ok']}, "
            f"призраков {stats.get('purged', 0)}\n"
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
    ok, msg = await nodes_db.set_primary_node(node_id)
    await safe_cb_answer(cb, "Основная нода обновлена" if ok else msg, show_alert=not ok)
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
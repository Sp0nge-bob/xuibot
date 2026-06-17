"""Админские хендлеры тикетов."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from db import tickets as tickets_db
from .admin_keyboards import (
    admin_back_kb,
    admin_ticket_detail_kb,
    admin_ticket_session_kb,
    admin_tickets_filter_kb,
    admin_tickets_kb,
)
from .states import AdminStates
from .ticket_chat import (
    clear_active_session,
    relay_ticket_message,
    set_active_session,
    get_active_session,
)
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_FILTER_LABELS = {
    "all": "Все",
    "refund": "Возврат",
    "support": "Поддержка",
    "other": "Другое",
}

_CAT_EMOJI = {
    tickets_db.CATEGORY_REFUND: "💸",
    tickets_db.CATEGORY_SUPPORT: "🛠",
    tickets_db.CATEGORY_OTHER: "📁",
}


def _user_label(username: str | None, first_name: str | None, tg_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return str(tg_id)


def _filter_category(filter_key: str) -> str | None:
    if filter_key == "all":
        return None
    return filter_key


async def _tickets_list_text(rows: list, filter_key: str) -> str:
    label = _FILTER_LABELS.get(filter_key, filter_key)
    if not rows:
        return f"🎫 <b>Тикеты — {label}</b>\n\nНет открытых тикетов."
    return (
        f"🎫 <b>Тикеты — {label}</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Открытых: <b>{len(rows)}</b>\n"
        "Выберите тикет:"
    )


@router.callback_query(F.data == "adm:tickets")
async def cb_admin_tickets_menu(cb: CallbackQuery):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🎫 <b>Тикеты</b>\n\nВыберите категорию:",
        admin_tickets_filter_kb(),
    )


@router.callback_query(F.data.startswith("adm:tickets:"))
async def cb_admin_tickets_list(cb: CallbackQuery, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    filter_key = cb.data.split(":")[2]
    category = _filter_category(filter_key)
    rows = await tickets_db.get_open_tickets(category=category)
    for row in rows:
        row["unread"] = await tickets_db.count_unread_for_admin(row["id"])
    text = await _tickets_list_text(rows, filter_key)
    kb = admin_tickets_kb(rows, filter_key=filter_key) if rows else admin_back_kb()
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, kb)


@router.callback_query(F.data.regexp(r"^adm:ticket:\d+$"))
async def cb_admin_ticket_detail(cb: CallbackQuery, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    ticket_id = int(cb.data.split(":")[2])
    row = await tickets_db.get_ticket_by_id(ticket_id)
    if not row or row.get("status") != tickets_db.STATUS_OPEN:
        await safe_cb_answer(cb, "Тикет не найден или закрыт", show_alert=True)
        return

    await tickets_db.mark_ticket_read_by_admin(ticket_id)
    label = _user_label(row.get("username"), row.get("first_name"), row["tg_id"])
    unread = await tickets_db.count_unread_for_admin(ticket_id)
    msg_count = len(await tickets_db.get_ticket_messages(ticket_id))
    cat = tickets_db.category_label(row["category"])
    lines = [
        f"🎫 <b>Тикет #{ticket_id}</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"📁 Категория: <b>{cat}</b>",
        f"👤 Пользователь: {label}",
        f"TG ID: <code>{row['tg_id']}</code>",
    ]
    if row.get("client_email"):
        lines.append(f"Клиент: <code>{row['client_email']}</code>")
        if row.get("sub_end_date"):
            lines.append(f"Подписка до: <b>{str(row['sub_end_date'])[:10]}</b>")
    if row.get("order_id"):
        lines += [
            "💳 <b>Оплата для возврата:</b>",
            f"🧾 ID заказа: <code>{row['order_id']}</code>",
            f"🆔 ID транзакции Platega: <code>{row.get('platega_tx_id') or '—'}</code>",
            f"Тариф: <b>{row.get('plan_name') or '—'}</b>",
            f"Сумма: <b>{row.get('order_amount') or '—'} ₽</b>",
        ]
    elif row.get("category") == tickets_db.CATEGORY_REFUND:
        lines.append("⚠️ Оплата не указана (старый тикет)")
    lines += [
        f"Создан: {(row.get('created_at') or '')[:16]}",
        f"💬 Сообщений: <b>{msg_count}</b>",
    ]
    if unread:
        lines.append(f"🔴 Непрочитанных: <b>{unread}</b>")
    await safe_cb_answer(cb)
    await send_or_edit(cb, "\n".join(lines), admin_ticket_detail_kb(ticket_id))


@router.callback_query(F.data.startswith("adm:ticket:session:"))
async def cb_admin_ticket_session(cb: CallbackQuery, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    ticket_id = int(cb.data.split(":")[3])
    row = await tickets_db.get_ticket_by_id(ticket_id)
    if not row or row.get("status") != tickets_db.STATUS_OPEN:
        await safe_cb_answer(cb, "Тикет закрыт", show_alert=True)
        return

    prev = set_active_session(cb.from_user.id, ticket_id)
    await state.set_state(AdminStates.in_ticket_chat)
    await state.update_data(ticket_chat_id=ticket_id)
    await tickets_db.mark_ticket_read_by_admin(ticket_id)

    label = _user_label(row.get("username"), row.get("first_name"), row["tg_id"])
    text = (
        f"🔴 <b>Переписка: тикет #{ticket_id}</b>\n"
        f"👤 {label} · {tickets_db.category_label(row['category'])}\n\n"
        "Отправляйте сообщения любого типа — они будут переданы клиенту.\n"
        "«Завершить переписку» — выйти из режима."
    )
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, admin_ticket_session_kb(ticket_id))
    if prev and prev != ticket_id:
        await cb.message.answer(f"ℹ️ Переключились на тикет #{ticket_id}")


@router.callback_query(F.data.startswith("adm:ticket:session_end:"))
async def cb_admin_ticket_session_end(cb: CallbackQuery, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    ticket_id = int(cb.data.split(":")[3])
    clear_active_session(cb.from_user.id, ticket_id=ticket_id)
    await state.set_state(None)
    await safe_cb_answer(cb, "Переписка завершена")
    row = await tickets_db.get_ticket_by_id(ticket_id)
    if row:
        await cb.message.answer(
            f"Тикет #{ticket_id} — сессия завершена.",
            reply_markup=admin_ticket_detail_kb(ticket_id),
        )


@router.callback_query(F.data.startswith("adm:ticket:close:"))
async def cb_admin_ticket_close(cb: CallbackQuery, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(cb.from_user.id):
        return
    ticket_id = int(cb.data.split(":")[3])
    closed = await tickets_db.close_ticket(ticket_id)
    if not closed:
        await safe_cb_answer(cb, "Тикет не найден или уже закрыт", show_alert=True)
        return

    clear_active_session(cb.from_user.id, ticket_id=ticket_id)
    await state.set_state(None)

    row = await tickets_db.get_ticket_by_id(ticket_id)
    if row:
        try:
            from bot import bot as tg_bot
            await tg_bot.send_message(
                row["tg_id"],
                f"✅ Тикет <code>#{ticket_id}</code> закрыт администратором.",
            )
        except Exception:
            pass

    await safe_cb_answer(cb, "Тикет закрыт")
    await send_or_edit(
        cb,
        "🎫 <b>Тикеты</b>\n\nВыберите категорию:",
        admin_tickets_filter_kb(),
    )


@router.message(AdminStates.in_ticket_chat)
async def msg_admin_ticket_relay(message: Message, state: FSMContext):
    from bot.admin import is_admin
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    ticket_id = data.get("ticket_chat_id")
    if not ticket_id:
        await state.clear()
        await message.answer("Сессия истекла. /admin")
        return

    if message.text and message.text.startswith("/"):
        if message.text.split("@")[0].lower() == "/admin":
            clear_active_session(message.from_user.id)
            await state.set_state(None)
            from bot.admin import _admin_menu_text, admin_menu_kb
            await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
        return

    ticket = await tickets_db.get_ticket_by_id(ticket_id)
    if not ticket or ticket.get("status") != tickets_db.STATUS_OPEN:
        await state.clear()
        clear_active_session(message.from_user.id, ticket_id=ticket_id)
        await message.answer("❌ Тикет закрыт.")
        return

    from bot import bot as tg_bot
    ok = await relay_ticket_message(
        message,
        ticket=ticket,
        is_admin=True,
        bot=tg_bot,
    )
    if not ok:
        await state.clear()
        clear_active_session(message.from_user.id, ticket_id=ticket_id)
        await message.answer("❌ Тикет закрыт.")
        return

    if get_active_session(message.from_user.id) == ticket_id:
        await message.answer(
            "✅ Отправлено",
            reply_markup=admin_ticket_session_kb(ticket_id),
        )
"""Пользовательские хендлеры тикетов."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config.trial import is_trial_email
from db import database as db
from db import tickets as tickets_db
from services.subscription_sync import get_active_subscriptions_for_ui
from .keyboards import (
    main_menu_kb,
    no_subscription_kb,
    back_to_main_kb,
    refund_confirm_kb,
    refund_pick_kb,
    subscription_manage_kb,
    subscriptions_manage_kb,
    support_menu_kb,
    ticket_category_kb,
    ticket_view_kb,
    ticket_session_kb,
)
from .messages import (
    no_subscription_text,
    refund_confirm_text,
    refund_pick_text,
    refund_request_sent_text,
    support_menu_text,
    ticket_session_banner_text,
    ticket_view_text,
)
from .states import UserStates
from .ticket_chat import (
    clear_active_session,
    relay_ticket_message,
    set_active_session,
    get_active_session,
)
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _message_command(text: str) -> str | None:
    raw = (text or "").strip().split()
    if not raw or not raw[0].startswith("/"):
        return None
    return raw[0].split("@")[0].lower()


async def _notify_admins_new_ticket(text: str) -> None:
    from config.settings import settings
    from bot import bot as tg_bot
    for admin_id in settings.BOT_ADMINS:
        try:
            await tg_bot.send_message(admin_id, text)
        except Exception:
            pass


async def _refund_ui_state(tg_id: int, sub_id: int) -> tuple[list[dict], bool]:
    """Открытые тикеты возврата по подписке и можно ли создать новый."""
    open_tickets = (
        await tickets_db.get_open_refund_tickets_by_subscription_for_user(tg_id)
    ).get(sub_id, [])
    blocked_orders = await tickets_db.get_refund_blocked_order_ids_for_subscription(sub_id)
    paid_orders = await db.get_paid_orders_for_user(tg_id)
    eligible = [o for o in paid_orders if o["id"] not in blocked_orders]
    return open_tickets, bool(eligible)


async def _eligible_refund_orders(tg_id: int, sub_id: int) -> list[dict]:
    blocked = await tickets_db.get_refund_blocked_order_ids_for_subscription(sub_id)
    paid = await db.get_paid_orders_for_subscription(sub_id)
    return [o for o in paid if o["tg_id"] == tg_id and o["id"] not in blocked]


async def _enter_ticket_session(
    cb: CallbackQuery | Message,
    state: FSMContext,
    ticket_id: int,
    *,
    is_new: bool = False,
) -> None:
    ticket = await tickets_db.get_ticket_by_id(ticket_id)
    if not ticket or ticket["tg_id"] != cb.from_user.id:
        if isinstance(cb, CallbackQuery):
            await safe_cb_answer(cb, "Тикет не найден", show_alert=True)
        return
    if ticket.get("status") != tickets_db.STATUS_OPEN:
        if isinstance(cb, CallbackQuery):
            await safe_cb_answer(cb, "Тикет закрыт", show_alert=True)
        return

    prev = set_active_session(cb.from_user.id, ticket_id)
    await state.set_state(UserStates.in_ticket_chat)
    await state.update_data(ticket_chat_id=ticket_id)

    text = ticket_session_banner_text(ticket_id, ticket["category"], is_new=is_new)
    kb = ticket_session_kb(ticket_id)
    if isinstance(cb, CallbackQuery):
        await safe_cb_answer(cb)
        await send_or_edit(cb, text, kb)
    else:
        if prev and prev != ticket_id:
            await cb.answer(f"Переключились на тикет #{ticket_id}")
        await cb.answer(text, reply_markup=kb)


@router.callback_query(F.data == "support")
async def cb_support_menu(cb: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    tickets = await tickets_db.get_user_open_tickets(cb.from_user.id)
    await safe_cb_answer(cb)
    await send_or_edit(cb, support_menu_text(tickets), support_menu_kb(tickets))


@router.callback_query(F.data == "ticket_create")
async def cb_ticket_create(cb: CallbackQuery):
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "📁 <b>Новое обращение</b>\n\nВыберите категорию:",
        ticket_category_kb(),
    )


@router.callback_query(F.data.startswith("ticket_new:"))
async def cb_ticket_new_category(cb: CallbackQuery, state: FSMContext):
    category = cb.data.split(":", 1)[1]
    if category not in (
        tickets_db.CATEGORY_SUPPORT,
        tickets_db.CATEGORY_OTHER,
    ):
        await safe_cb_answer(cb, "Неизвестная категория", show_alert=True)
        return

    ticket_id = await tickets_db.create_ticket(
        tg_id=cb.from_user.id,
        category=category,
    )
    cat_label = tickets_db.category_label(category)
    await _notify_admins_new_ticket(
        f"🎫 <b>Новый тикет #{ticket_id}</b>\n"
        f"👤 {cb.from_user.username or cb.from_user.first_name or cb.from_user.id}\n"
        f"📁 {cat_label}\n\n"
        f"💬 /admin → Тикеты → #{ticket_id}"
    )
    await _enter_ticket_session(cb, state, ticket_id, is_new=True)


@router.callback_query(F.data.startswith("support_from_order:"))
async def cb_support_from_order(cb: CallbackQuery, state: FSMContext):
    order_id = int(cb.data.split(":", 1)[1])
    order = await db.get_order_by_id(order_id)
    if not order or order["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Заказ не найден", show_alert=True)
        return

    ticket_id = await tickets_db.create_ticket(
        tg_id=cb.from_user.id,
        category=tickets_db.CATEGORY_SUPPORT,
        order_id=order_id,
    )
    await _notify_admins_new_ticket(
        f"🎫 <b>Новый тикет #{ticket_id}</b> (проблема с оплатой)\n"
        f"👤 <code>{cb.from_user.id}</code>\n"
        f"🧾 Заказ <code>#{order_id}</code> · {order.get('plan_name')} · {order.get('amount')} ₽\n"
        f"🆔 TX: <code>{order.get('platega_tx_id')}</code>\n\n"
        f"💬 /admin → Тикеты → #{ticket_id}"
    )
    await _enter_ticket_session(cb, state, ticket_id, is_new=True)


@router.callback_query(F.data.startswith("ticket_view:"))
async def cb_ticket_view(cb: CallbackQuery, state: FSMContext):
    ticket_id = int(cb.data.split(":", 1)[1])
    ticket = await tickets_db.get_ticket_by_id(ticket_id)
    if not ticket or ticket["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Тикет не найден", show_alert=True)
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        ticket_view_text(ticket),
        ticket_view_kb(
            ticket_id,
            is_open=ticket["status"] == tickets_db.STATUS_OPEN,
            is_refund=ticket.get("category") == tickets_db.CATEGORY_REFUND,
        ),
    )


@router.callback_query(F.data.startswith("ticket_session:"))
async def cb_ticket_session(cb: CallbackQuery, state: FSMContext):
    ticket_id = int(cb.data.split(":", 1)[1])
    prev = get_active_session(cb.from_user.id)
    await _enter_ticket_session(cb, state, ticket_id)
    if prev and prev != ticket_id:
        await cb.message.answer(f"ℹ️ Переключились на тикет #{ticket_id}")


@router.callback_query(F.data.startswith("ticket_session_end:"))
async def cb_ticket_session_end(cb: CallbackQuery, state: FSMContext):
    ticket_id = int(cb.data.split(":", 1)[1])
    clear_active_session(cb.from_user.id, ticket_id=ticket_id)
    await state.set_state(None)
    await safe_cb_answer(cb, "Переписка завершена")
    ticket = await tickets_db.get_ticket_by_id(ticket_id)
    if ticket:
        await send_or_edit(
            cb,
            ticket_view_text(ticket),
            ticket_view_kb(
                ticket_id,
                is_open=ticket["status"] == tickets_db.STATUS_OPEN,
                is_refund=ticket.get("category") == tickets_db.CATEGORY_REFUND,
            ),
        )


@router.callback_query(F.data.regexp(r"^refund:\d+$"))
async def cb_refund(cb: CallbackQuery):
    sub_id = int(cb.data.split(":", 1)[1])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return
    if not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка неактивна", show_alert=True)
        return

    orders = await _eligible_refund_orders(cb.from_user.id, sub_id)
    if not orders:
        await safe_cb_answer(cb, "Нет оплат для возврата", show_alert=True)
        return

    await safe_cb_answer(cb)
    if len(orders) == 1:
        order = orders[0]
        await send_or_edit(
            cb,
            refund_confirm_text(order),
            refund_confirm_kb(sub_id, order["id"]),
        )
        return
    await send_or_edit(cb, refund_pick_text(), refund_pick_kb(sub_id, orders))


@router.callback_query(F.data.regexp(r"^refund_pick:\d+:\d+$"))
async def cb_refund_pick(cb: CallbackQuery):
    parts = cb.data.split(":")
    sub_id = int(parts[1])
    order_id = int(parts[2])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return
    order = await db.get_order_by_id(order_id)
    if not order or order["tg_id"] != cb.from_user.id or order.get("status") != "paid":
        await safe_cb_answer(cb, "Оплата не найдена", show_alert=True)
        return
    existing = await tickets_db.get_open_refund_ticket_for_order(sub_id, order_id)
    if existing:
        await safe_cb_answer(cb, "Возврат по этой оплате уже открыт", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        refund_confirm_text(order),
        refund_confirm_kb(sub_id, order_id),
    )


@router.callback_query(F.data.regexp(r"^refund_confirm:\d+:\d+$"))
async def cb_refund_confirm(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split(":")
    sub_id = int(parts[1])
    order_id = int(parts[2])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return
    if not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка неактивна", show_alert=True)
        return
    order = await db.get_order_by_id(order_id)
    if not order or order["tg_id"] != cb.from_user.id or order.get("status") != "paid":
        await safe_cb_answer(cb, "Оплата не найдена", show_alert=True)
        return
    if await tickets_db.has_approved_refund_for_order(sub_id, order_id):
        await safe_cb_answer(cb, "Возврат по этому заказу уже одобрен", show_alert=True)
        return
    if order_id in await tickets_db.get_refund_blocked_order_ids_for_subscription(sub_id):
        await safe_cb_answer(cb, "Запрос на возврат уже отправлен", show_alert=True)
        return

    ticket_id = await tickets_db.create_ticket(
        tg_id=cb.from_user.id,
        category=tickets_db.CATEGORY_REFUND,
        subscription_id=sub_id,
        order_id=order_id,
    )
    from .messages import refund_admin_text
    await _notify_admins_new_ticket(
        refund_admin_text(
            cb.from_user.id,
            cb.from_user.username,
            cb.from_user.first_name,
            sub,
            order,
        )
        + f"\n\n🎫 Тикет <code>#{ticket_id}</code> · /admin → Тикеты"
    )
    await safe_cb_answer(cb, "Запрос отправлен")
    await send_or_edit(cb, refund_request_sent_text(ticket_id), back_to_main_kb())


@router.message(UserStates.in_ticket_chat)
async def msg_ticket_relay(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("ticket_chat_id")
    if not ticket_id:
        await state.clear()
        await message.answer("Сессия истекла.")
        return

    if message.text:
        cmd = _message_command(message.text)
        if cmd == "/start":
            clear_active_session(message.from_user.id)
            await state.clear()
            from .handlers import _show_main_menu
            await _show_main_menu(message, state=state)
            return
        if cmd == "/subscription":
            clear_active_session(message.from_user.id)
            await state.clear()
            await show_subscriptions_manage(message, message.from_user.id)
            return
        if cmd == "/faq":
            clear_active_session(message.from_user.id)
            await state.clear()
            from .faq import show_faq_menu_message

            await show_faq_menu_message(message)
            return
        if cmd:
            return

    ticket = await tickets_db.get_ticket_by_id(ticket_id)
    if not ticket or ticket["tg_id"] != message.from_user.id:
        await state.clear()
        clear_active_session(message.from_user.id)
        await message.answer("Тикет недоступен.")
        return

    from bot import bot as tg_bot
    ok = await relay_ticket_message(
        message,
        ticket=ticket,
        is_admin=False,
        bot=tg_bot,
    )
    if not ok:
        await state.clear()
        clear_active_session(message.from_user.id, ticket_id=ticket_id)
        await message.answer("❌ Тикет закрыт.", reply_markup=back_to_main_kb())
        return

    if ticket_id and get_active_session(message.from_user.id) == ticket_id:
        await message.answer("✅ Отправлено", reply_markup=ticket_session_kb(ticket_id))


async def show_subscription_detail(
    target: Message | CallbackQuery,
    tg_id: int,
    sub_id: int,
) -> None:
    from .messages import subscription_manage_text
    from services.limit_ip import resolve_limit_ip_for_email
    from services.xui import build_sub_link

    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != tg_id or not sub.get("is_active"):
        text, kb = no_subscription_text(), no_subscription_kb()
        if isinstance(target, CallbackQuery):
            await safe_cb_answer(target, "Подписка не найдена", show_alert=True)
            await send_or_edit(target, text, kb)
        else:
            await target.answer(text, reply_markup=kb)
        return

    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)

    refund_by_sub = await tickets_db.get_open_refund_tickets_by_subscription_for_user(tg_id)
    extend_blocked = await tickets_db.is_extend_blocked_by_pending_refund(tg_id)
    can_refund = False
    if not is_trial_email(sub.get("client_email")):
        _, can_refund = await _refund_ui_state(tg_id, sub_id)

    limit_ip = await resolve_limit_ip_for_email(sub.get("client_email") or "")
    sub_link = await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
    text = subscription_manage_text(sub, sub_link, limit_ip=limit_ip)
    kb = subscription_manage_kb(
        sub_id,
        refund_tickets=refund_by_sub.get(sub_id, []),
        can_request_refund=can_refund,
        can_extend=not extend_blocked,
        is_trial=is_trial_email(sub.get("client_email")),
        back_callback="manage_sub",
    )
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def show_subscriptions_manage(
    target: Message | CallbackQuery,
    tg_id: int,
) -> None:
    """Экспорт для handlers.py — главное меню «Подписка» и /subscription."""
    from .messages import subscription_manage_text, subscriptions_manage_text
    from services.limit_ip import resolve_limit_ip_for_email
    from services.xui import build_sub_link

    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)

    subs = await get_active_subscriptions_for_ui(tg_id)
    if not subs:
        text, kb = no_subscription_text(), no_subscription_kb()
        if isinstance(target, CallbackQuery):
            await send_or_edit(target, text, kb)
        else:
            await target.answer(text, reply_markup=kb)
        return

    refund_by_sub = await tickets_db.get_open_refund_tickets_by_subscription_for_user(tg_id)
    extend_blocked = await tickets_db.is_extend_blocked_by_pending_refund(tg_id)
    can_refund: dict[int, bool] = {}
    for sub in subs:
        if is_trial_email(sub.get("client_email")):
            continue
        _, can_refund[sub["id"]] = await _refund_ui_state(tg_id, sub["id"])

    limit_ips: dict[int, int] = {}
    for sub in subs:
        limit_ips[sub["id"]] = await resolve_limit_ip_for_email(sub.get("client_email") or "")

    if len(subs) == 1:
        sub = subs[0]
        sub_link = await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
        text = subscription_manage_text(sub, sub_link, limit_ip=limit_ips.get(sub["id"]))
        kb = subscription_manage_kb(
            sub["id"],
            refund_tickets=refund_by_sub.get(sub["id"], []),
            can_request_refund=can_refund.get(sub["id"], False),
            can_extend=not extend_blocked,
            is_trial=is_trial_email(sub.get("client_email")),
        )
        if isinstance(target, CallbackQuery):
            await send_or_edit(target, text, kb)
        else:
            await target.answer(text, reply_markup=kb)
        return

    sub_links = {}
    for sub in subs:
        sub_links[sub["id"]] = (
            await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
        )
    text = subscriptions_manage_text(subs, sub_links, limit_ips=limit_ips)
    kb = subscriptions_manage_kb(
        subs,
        refund_tickets=refund_by_sub,
        can_request_refund=can_refund,
        can_extend=not extend_blocked,
    )
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)
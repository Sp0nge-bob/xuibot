"""Админские инструменты отладки."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from db import database as db
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db import tickets as tickets_db
from db import trial_grants as trial_db
from services.xui import remove_client_everywhere
from services.bot_lockdown import get_lockdown_status, get_whitelist
from services.test_mode import (
    clear_test_mode_override,
    is_test_mode,
    is_test_mode_overridden,
    set_test_mode,
    test_mode_source_label,
)
from .admin_auth import is_debug_admin
from .admin_keyboards import (
    admin_back_kb,
    admin_debug_entry_confirm_kb,
    admin_debug_kb,
    admin_debug_order_detail_kb,
    admin_debug_order_message_kb,
    admin_debug_orders_kb,
    admin_debug_orders_list_kb,
    admin_debug_orders_reset_confirm_kb,
    admin_debug_promo_reset_confirm_kb,
    admin_debug_tickets_reset_confirm_kb,
    admin_debug_users_reset_confirm_kb,
)
from .messages import (
    admin_debug_entry_confirm_text,
    admin_debug_menu_text,
    admin_debug_order_detail_text,
    admin_debug_order_user_message_prompt_text,
    admin_debug_order_user_message_to_client,
    admin_debug_orders_list_text,
    admin_debug_orders_menu_text,
    admin_debug_orders_reset_confirm_text,
    admin_debug_promo_reset_confirm_text,
    admin_debug_tickets_reset_confirm_text,
    admin_debug_users_reset_confirm_text,
)
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_ORDERS_PAGE_SIZE = 6
_ORDER_STATUSES = frozenset({"paid", "failed"})


def _parse_orders_list_cb(data: str) -> tuple[str, int]:
    parts = (data or "").split(":")
    if len(parts) >= 6 and parts[4] in _ORDER_STATUSES:
        return parts[4], int(parts[5])
    if len(parts) >= 5:
        return "paid", int(parts[4])
    return "paid", 0


def _parse_orders_view_cb(data: str) -> tuple[str, int, int]:
    parts = (data or "").split(":")
    if len(parts) >= 7 and parts[4] in _ORDER_STATUSES:
        return parts[4], int(parts[5]), int(parts[6])
    if len(parts) >= 6:
        return "paid", int(parts[4]), int(parts[5])
    return "paid", 0, 0


def _parse_orders_msg_cb(data: str) -> tuple[str, int, int]:
    parts = (data or "").split(":")
    if len(parts) >= 7 and parts[4] in _ORDER_STATUSES:
        return parts[4], int(parts[5]), int(parts[6])
    return "failed", 0, 0


async def _enrich_order(order: dict) -> dict:
    if not order:
        return order
    user = await db.get_user(int(order["tg_id"])) if order.get("tg_id") else None
    if user:
        return {**order, "username": user.get("username"), "first_name": user.get("first_name")}
    return order


async def _orders_stats() -> dict[str, int]:
    total = await db.count_orders()
    paid = await db.count_orders_by_status("paid")
    pending = await db.count_orders_by_status("pending")
    failed = await db.count_orders_by_status("failed")
    return {
        "total": total,
        "paid": paid,
        "pending": pending,
        "failed": failed,
    }


async def _debug_kb():
    test_mode = await is_test_mode()
    overridden = await is_test_mode_overridden()
    lockdown = await get_lockdown_status()
    return admin_debug_kb(
        test_mode=test_mode,
        test_mode_overridden=overridden,
        lockdown_active=lockdown.restricted,
    )


async def _show_debug_menu(cb: CallbackQuery) -> None:
    trial_count = await db.count_active_trial_subscriptions()
    promo_uses = await promo_db.count_promo_uses()
    promo_pending = await pending_db.count_pending_discounts()
    orders_count = await db.count_orders()
    tickets_count = await tickets_db.count_tickets()
    ticket_messages_count = await tickets_db.count_ticket_messages()
    users_count = await db.count_users()
    test_mode = await is_test_mode()
    test_mode_source = await test_mode_source_label()
    lockdown = await get_lockdown_status()
    whitelist_count = len(await get_whitelist())
    await send_or_edit(
        cb,
        admin_debug_menu_text(
            trial_count=trial_count,
            promo_uses=promo_uses,
            promo_pending=promo_pending,
            orders_count=orders_count,
            tickets_count=tickets_count,
            ticket_messages_count=ticket_messages_count,
            users_count=users_count,
            test_mode=test_mode,
            test_mode_source=test_mode_source,
            lockdown_summary=lockdown.summary_label,
            lockdown_whitelist_count=whitelist_count,
        ),
        await _debug_kb(),
    )


@router.callback_query(F.data == "adm:debug")
async def cb_admin_debug_entry(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_debug_entry_confirm_text(), admin_debug_entry_confirm_kb())


@router.callback_query(F.data == "adm:debug:enter")
async def cb_admin_debug_menu(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_debug_menu(cb)


@router.callback_query(F.data == "adm:debug:test_mode_toggle")
async def cb_admin_debug_test_mode_toggle(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    current = await is_test_mode()
    await set_test_mode(not current)
    label = "включён" if not current else "выключен"
    await safe_cb_answer(cb, f"TEST_MODE {label}")
    await _show_debug_menu(cb)


@router.callback_query(F.data == "adm:debug:test_mode_reset")
async def cb_admin_debug_test_mode_reset(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    await clear_test_mode_override()
    await safe_cb_answer(cb, "TEST_MODE из .env")
    await _show_debug_menu(cb)


@router.callback_query(F.data == "adm:debug:promos_reset")
async def cb_admin_debug_promos_reset_confirm(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    uses_count = await promo_db.count_promo_uses()
    pending_count = await pending_db.count_pending_discounts()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_promo_reset_confirm_text(
            uses_count=uses_count,
            pending_count=pending_count,
        ),
        admin_debug_promo_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:promos_reset:confirm")
async def cb_admin_debug_promos_reset(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Очищаем…")
    try:
        result = await promo_db.reset_all_promo_applications()
    except Exception as e:
        logger.exception("Promo reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Применения промокодов очищены</b>\n\n"
        f"Удалено promo_uses: <b>{result['uses_deleted']}</b>\n"
        f"Удалено pending: <b>{result['pending_deleted']}</b>\n"
        "Счётчики <code>used_count</code> обнулены."
    )
    await send_or_edit(cb, text, await _debug_kb())


@router.callback_query(F.data == "adm:debug:orders")
async def cb_admin_debug_orders_menu(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    stats = await _orders_stats()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_orders_menu_text(
            total_count=stats["total"],
            paid_count=stats["paid"],
            pending_count=stats["pending"],
            failed_count=stats["failed"],
        ),
        admin_debug_orders_kb(failed_count=stats["failed"]),
    )


@router.callback_query(F.data.startswith("adm:debug:orders:list:"))
async def cb_admin_debug_orders_list(cb: CallbackQuery, state: FSMContext):
    if not is_debug_admin(cb.from_user.id):
        return

    await state.set_state(None)
    status, page = _parse_orders_list_cb(cb.data or "")
    total_count = await db.count_orders_by_status(status)
    orders = await db.list_orders(
        status=status,
        limit=_ORDERS_PAGE_SIZE,
        offset=page * _ORDERS_PAGE_SIZE,
    )
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_orders_list_text(
            orders,
            status=status,
            page=page,
            total_count=total_count,
            page_size=_ORDERS_PAGE_SIZE,
        ),
        admin_debug_orders_list_kb(
            orders,
            status=status,
            page=page,
            page_size=_ORDERS_PAGE_SIZE,
            total_count=total_count,
        ),
    )


@router.callback_query(F.data.startswith("adm:debug:orders:view:"))
async def cb_admin_debug_order_detail(cb: CallbackQuery, state: FSMContext):
    if not is_debug_admin(cb.from_user.id):
        return

    await state.set_state(None)
    status, order_id, page = _parse_orders_view_cb(cb.data or "")
    order = await _enrich_order(await db.get_order_by_id(order_id))
    if not order:
        await safe_cb_answer(cb, "Заказ не найден", show_alert=True)
        return

    can_message = (
        status == "failed"
        and (order.get("status") or "").strip() == "failed"
        and bool(order.get("tg_id"))
    )
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_order_detail_text(order),
        admin_debug_order_detail_kb(
            order_id=order_id,
            status=status,
            page=page,
            can_message=can_message,
        ),
    )


@router.callback_query(F.data.startswith("adm:debug:orders:msg:"))
async def cb_admin_debug_order_message_start(cb: CallbackQuery, state: FSMContext):
    if not is_debug_admin(cb.from_user.id):
        return

    status, order_id, page = _parse_orders_msg_cb(cb.data or "")
    order = await _enrich_order(await db.get_order_by_id(order_id))
    if not order:
        await safe_cb_answer(cb, "Заказ не найден", show_alert=True)
        return
    if (order.get("status") or "").strip() != "failed":
        await safe_cb_answer(cb, "Сообщение доступно только для неудачных заказов", show_alert=True)
        return
    if not order.get("tg_id"):
        await safe_cb_answer(cb, "У заказа нет TG ID", show_alert=True)
        return

    await state.set_state(AdminStates.in_order_user_message)
    await state.update_data(
        order_user_msg_order_id=order_id,
        order_user_msg_status=status,
        order_user_msg_page=page,
    )
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_order_user_message_prompt_text(order),
        admin_debug_order_message_kb(order_id=order_id, status=status, page=page),
    )


@router.message(AdminStates.in_order_user_message)
async def msg_admin_debug_order_user_message(message: Message, state: FSMContext):
    if not is_debug_admin(message.from_user.id):
        return

    data = await state.get_data()
    order_id = int(data.get("order_user_msg_order_id") or 0)
    status = str(data.get("order_user_msg_status") or "failed")
    page = int(data.get("order_user_msg_page") or 0)
    if not order_id:
        await state.set_state(None)
        await message.answer("Сессия истекла. Откройте заказ снова.")
        return

    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Отправьте текстовое сообщение.")
        return
    if raw.startswith("/"):
        cmd = raw.split()[0].split("@")[0].lower()
        if cmd == "/admin":
            await state.set_state(None)
            from bot.admin import _admin_menu_text, admin_menu_kb
            await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
        return

    order = await _enrich_order(await db.get_order_by_id(order_id))
    if not order or (order.get("status") or "").strip() != "failed":
        await state.set_state(None)
        await message.answer("❌ Заказ не найден или уже не в статусе failed.")
        return

    tg_id = int(order["tg_id"])
    text = admin_debug_order_user_message_to_client(order, raw)
    try:
        from bot import bot as tg_bot
        await tg_bot.send_message(tg_id, text)
    except Exception as e:
        logger.warning("Failed order message to {}: {}", tg_id, e)
        await message.answer(
            f"❌ Не удалось отправить: <code>{type(e).__name__}</code>",
            reply_markup=admin_debug_order_message_kb(
                order_id=order_id, status=status, page=page,
            ),
        )
        return

    await message.answer(
        f"✅ Сообщение отправлено клиенту <code>{tg_id}</code>",
        reply_markup=admin_debug_order_message_kb(
            order_id=order_id, status=status, page=page,
        ),
    )


@router.callback_query(F.data == "adm:debug:orders_reset")
async def cb_admin_debug_orders_reset_confirm(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    orders_count = await db.count_orders()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_orders_reset_confirm_text(orders_count=orders_count),
        admin_debug_orders_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:orders_reset:confirm")
async def cb_admin_debug_orders_reset(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    try:
        result = await db.reset_all_orders()
    except Exception as e:
        logger.exception("Orders reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>История заказов очищена</b>\n\n"
        f"Удалено заказов: <b>{result['orders_deleted']}</b>\n"
        f"Тикетов отвязано от заказов: <b>{result['tickets_unlinked']}</b>"
    )
    await send_or_edit(cb, text, await _debug_kb())


@router.callback_query(F.data == "adm:debug:tickets_reset")
async def cb_admin_debug_tickets_reset_confirm(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    tickets_count = await tickets_db.count_tickets()
    messages_count = await tickets_db.count_ticket_messages()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_tickets_reset_confirm_text(
            tickets_count=tickets_count,
            messages_count=messages_count,
        ),
        admin_debug_tickets_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:tickets_reset:confirm")
async def cb_admin_debug_tickets_reset(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    try:
        result = await tickets_db.reset_all_tickets()
    except Exception as e:
        logger.exception("Tickets reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Учёт тикетов очищен</b>\n\n"
        f"Удалено тикетов: <b>{result['tickets_deleted']}</b>\n"
        f"Удалено сообщений: <b>{result['messages_deleted']}</b>"
    )
    await send_or_edit(cb, text, await _debug_kb())


@router.callback_query(F.data == "adm:debug:users_reset")
async def cb_admin_debug_users_reset_confirm(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    users_count = await db.count_users()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_debug_users_reset_confirm_text(users_count=users_count),
        admin_debug_users_reset_confirm_kb(),
    )


@router.callback_query(F.data == "adm:debug:users_reset:confirm")
async def cb_admin_debug_users_reset(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return

    await safe_cb_answer(cb, "Удаляем…")
    await send_or_edit(cb, "⏳ Удаляем пользователей и подписки с панели…")
    panel_removed = 0
    panel_errors = 0
    try:
        subs = await db.get_all_active_subscriptions()
        for sub in subs:
            email = sub.get("client_email")
            if not email:
                continue
            try:
                await remove_client_everywhere(email)
                panel_removed += 1
            except Exception as e:
                panel_errors += 1
                logger.error(
                    "Users reset: panel remove failed for #{} ({}): {}",
                    sub.get("id"),
                    email,
                    e,
                )
        result = await db.reset_all_users()
        grants_deleted = await trial_db.reset_all_trial_grants()
    except Exception as e:
        logger.exception("Users reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    text = (
        "✅ <b>Учёт пользователей очищен</b>\n\n"
        f"Удалено users: <b>{result['users_deleted']}</b>\n"
        f"Деактивировано подписок: <b>{result.get('subs_deactivated', 0)}</b>\n"
        f"С панели 3x-ui: <b>{panel_removed}</b>"
    )
    if panel_errors:
        text += f"\nОшибок на панели: <b>{panel_errors}</b>"
    if grants_deleted:
        text += f"\nСброшено пробных лимитов: <b>{grants_deleted}</b>"
    await send_or_edit(cb, text, await _debug_kb())
import re

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from db import promo_codes as promo_db
from db.plan_prices import set_plan_price
from services.pricing import list_plans
from config.plans import get_plan
from db import trial_grants as trial_db
from .messages import (
    admin_plans_text,
    admin_promos_text,
    admin_promo_detail_text,
    admin_trial_menu_text,
    admin_trial_reset_confirm_text,
)
from services.trial import admin_reset_trial
from .states import AdminPricingStates, AdminStates
from .refund_chat import format_refund_chat_history, store_and_deliver_refund_message
from services.subscription_admin import admin_delete_subscription
from .admin_users import (
    admin_users_category_text,
    admin_users_menu_text,
    admin_users_search_text,
    split_connected_users,
    subscription_kind_label,
)
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_menu_kb,
    admin_back_kb,
    admin_plans_kb,
    admin_promos_kb,
    admin_promo_detail_kb,
    admin_users_kb,
    admin_users_menu_kb,
    admin_users_search_kb,
    admin_user_detail_kb,
    admin_delete_confirm_kb,
    admin_refunds_kb,
    admin_refund_detail_kb,
    admin_refund_chat_kb,
    admin_trial_kb,
    admin_trial_reset_confirm_kb,
)
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _user_label(username: str | None, first_name: str | None, tg_id: int) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return str(tg_id)


def _admin_stats_block(stats: dict[str, int]) -> str:
    return (
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"✅ Платных подписок: <b>{stats['paid_subs']}</b>\n"
        f"🎁 Пробных подписок: <b>{stats['trial_subs']}</b>\n"
        f"💰 Оплаченных заказов: <b>{stats['paid_orders']}</b>\n"
        f"💸 Запросов на возврат: <b>{stats['pending_refunds']}</b>"
    )


async def _admin_menu_text() -> str:
    stats = await db.get_admin_stats()
    summary = await nodes_db.nodes_summary()
    primary = await nodes_db.get_primary_node()
    primary_name = primary["name"] if primary else "—"
    primary_inbounds = primary.get("inbound_ids") if primary else "—"
    nodes_line = (
        f"🖧 Ноды: <b>{summary['total']}</b> "
        f"(healthy <b>{summary['healthy']}</b>/<b>{summary['enabled']}</b>)"
    )
    return (
        "🛠 <b>Админ-панель</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{_admin_stats_block(stats)}\n\n"
        f"{nodes_line}\n"
        f"★ Основная: <b>{primary_name}</b> · inbounds: <code>{primary_inbounds or '—'}</code>\n"
        f"Группа 3x-ui: <code>{settings.XUI_CLIENT_GROUP}</code>\n\n"
        "Выберите раздел:"
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(None)
    await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    await send_or_edit(cb, await _admin_menu_text(), admin_menu_kb())


@router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    stats = await db.get_admin_stats()
    summary = await nodes_db.nodes_summary()
    primary = await nodes_db.get_primary_node()
    text = (
        "📊 <b>Статистика</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{_admin_stats_block(stats)}\n\n"
        f"🖧 Ноды: <b>{summary['total']}</b> · healthy <b>{summary['healthy']}</b>"
        f"/<b>{summary['enabled']}</b>\n"
        f"★ Основная: <b>{primary['name'] if primary else '—'}</b>"
    )
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, admin_back_kb())


_USERS_LIST_LIMIT = 25


async def _show_admin_users_menu(cb: CallbackQuery, state: FSMContext) -> None:
    paid_count = await db.count_connected_users(trial_only=False)
    trial_count = await db.count_connected_users(trial_only=True)
    await state.update_data(admin_user_from_search=False, admin_user_category=None)
    await send_or_edit(
        cb,
        admin_users_menu_text(paid_count=paid_count, trial_count=trial_count),
        admin_users_menu_kb(paid_count=paid_count, trial_count=trial_count),
    )


async def _show_admin_users_category(
    cb: CallbackQuery,
    state: FSMContext,
    *,
    category: str,
) -> None:
    trial_only = category == "trial"
    users = await db.get_connected_users(_USERS_LIST_LIMIT, trial_only=trial_only)
    await state.update_data(
        admin_user_from_search=False,
        admin_user_category=category,
    )
    await send_or_edit(
        cb,
        admin_users_category_text(
            category=category,
            users=users,
            limit=_USERS_LIST_LIMIT,
        ),
        admin_users_kb(users, category=category),
    )


@router.callback_query(F.data == "adm:users")
async def cb_admin_users(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_admin_users_menu(cb, state)


@router.callback_query(F.data == "adm:users:paid")
async def cb_admin_users_paid(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_admin_users_category(cb, state, category="paid")


@router.callback_query(F.data == "adm:users:trial")
async def cb_admin_users_trial(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_admin_users_category(cb, state, category="trial")


@router.callback_query(F.data == "adm:users:search")
async def cb_admin_users_search(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_user_search)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🔍 <b>Поиск подписки</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте:\n"
        "• <code>@username</code> или <code>username</code>\n"
        "• <code>123456789</code> — Telegram ID\n"
        "• <code>tg123456789</code> — платный клиент\n"
        "• <code>tgfree123456789</code> — пробный клиент\n\n"
        "Для отмены: /admin",
        admin_back_kb(),
    )


@router.message(AdminStates.waiting_user_search)
async def msg_admin_user_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("❌ Введите @username, TG ID или email.")
        return

    users = await db.search_connected_users(query, limit=25)
    await state.set_state(None)
    await state.update_data(admin_user_from_search=True)

    paid, trial = split_connected_users(users)
    if not paid and not trial:
        await message.answer(
            f"🔍 По запросу <code>{query}</code> активных подписок не найдено.",
            reply_markup=admin_users_search_kb([], []),
        )
        return

    if len(users) == 1:
        u = users[0]
        sub_id = u["subscription_id"]
        label = _user_label(u.get("username"), u.get("first_name"), u["tg_id"])
        kind = subscription_kind_label(u.get("client_email"))
        text = (
            "🔍 <b>Найден 1 пользователь</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"Тип: {kind}\n"
            f"Имя: {label}\n"
            f"TG ID: <code>{u['tg_id']}</code>\n"
            f"Подписка: <code>#{sub_id}</code>\n"
            f"Клиент: <code>{u['client_email']}</code>\n"
            f"До: <b>{u['end_date'][:10]}</b>"
        )
        await message.answer(
            text,
            reply_markup=admin_user_detail_kb(sub_id, u["tg_id"], from_search=True),
        )
        return

    await message.answer(
        admin_users_search_text(query, paid, trial),
        reply_markup=admin_users_search_kb(paid, trial),
    )


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_admin_user_detail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    sub_id = int(parts[2])
    from_search = len(parts) > 3 and parts[3] == "search"
    if from_search:
        await state.update_data(admin_user_from_search=True)
    else:
        data = await state.get_data()
        from_search = bool(data.get("admin_user_from_search"))
    category = (await state.get_data()).get("admin_user_category")
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return

    user = await db.get_or_create_user(sub["tg_id"])
    label = _user_label(user.get("username"), user.get("first_name"), sub["tg_id"])
    kind = subscription_kind_label(sub.get("client_email"))
    text = (
        "👤 <b>Пользователь</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Тип: {kind}\n"
        f"Имя: {label}\n"
        f"TG ID: <code>{sub['tg_id']}</code>\n"
        f"Подписка: <code>#{sub_id}</code>\n"
        f"Клиент: <code>{sub['client_email']}</code>\n"
        f"До: <b>{sub['end_date'][:10]}</b>\n"
        f"subId: <code>{sub.get('sub_id') or '—'}</code>"
    )
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        text,
        admin_user_detail_kb(
            sub_id,
            sub["tg_id"],
            from_search=from_search,
            category=category,
        ),
    )


@router.callback_query(F.data.startswith("adm:del_sub:") & ~F.data.startswith("adm:del_sub:confirm:"))
async def cb_admin_delete_sub_confirm(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    sub_id = int(cb.data.split(":", 2)[2])
    from_search = bool((await state.get_data()).get("admin_user_from_search"))
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return

    text = (
        "🗑 <b>Удаление подписки</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Клиент: <code>{sub['client_email']}</code>\n"
        f"TG ID: <code>{sub['tg_id']}</code>\n\n"
        "Клиент будет удалён из панели 3x-ui,\n"
        "подписка деактивирована в БД бота.\n\n"
        "⚠️ Действие необратимо."
    )
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, admin_delete_confirm_kb(sub_id, from_search=from_search))


@router.callback_query(F.data.startswith("adm:del_sub:confirm:"))
async def cb_admin_delete_sub(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    sub_id = int(cb.data.split(":", 3)[3])
    await safe_cb_answer(cb, "Удаляем...")
    await send_or_edit(cb, "⏳ Удаление подписки...")

    try:
        result = await admin_delete_subscription(sub_id)
    except ValueError as e:
        await send_or_edit(cb, f"❌ {e}", admin_back_kb())
        return
    except Exception as e:
        await send_or_edit(
            cb,
            f"❌ Ошибка удаления: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    removed = result["removed_inbounds"]
    removed_text = ", ".join(str(x) for x in removed) if removed else "—"
    text = (
        "✅ <b>Подписка удалена</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Клиент: <code>{result['email']}</code>\n"
        f"TG ID: <code>{result['tg_id']}</code>\n"
        f"Удалено из инбаундов: <code>{removed_text}</code>"
    )
    await send_or_edit(cb, text, admin_back_kb())


@router.callback_query(F.data == "adm:refunds")
async def cb_admin_refunds(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    rows = await db.get_pending_refunds()
    if not rows:
        text = "💸 <b>Запросы на возврат</b>\n\nНет открытых запросов."
        kb = admin_back_kb()
    else:
        text = (
            "💸 <b>Запросы на возврат</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"Открытых: <b>{len(rows)}</b>\n"
            "Выберите запрос для просмотра и закрытия:"
        )
        kb = admin_refunds_kb(rows)
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, kb)


@router.callback_query(F.data.startswith("adm:refund:chat:"))
async def cb_admin_refund_chat(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    refund_id = int(cb.data.split(":")[3])
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row.get("status") != "pending":
        await safe_cb_answer(cb, "Запрос не найден или уже закрыт", show_alert=True)
        return

    messages = await db.get_refund_messages(refund_id)
    text = format_refund_chat_history(messages, refund_id=refund_id, for_admin=True)
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, admin_refund_chat_kb(refund_id))


@router.callback_query(F.data.startswith("adm:refund:reply:"))
async def cb_admin_refund_reply_start(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    refund_id = int(cb.data.split(":")[3])
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row.get("status") != "pending":
        await safe_cb_answer(cb, "Запрос закрыт", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_refund_reply)
    await state.update_data(refund_chat_id=refund_id)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"✏️ <b>Ответ по возврату #{refund_id}</b>\n\n"
        "Отправьте сообщение пользователю.\n"
        "Для отмены: /admin",
        admin_refund_chat_kb(refund_id),
    )


@router.message(AdminStates.waiting_refund_reply)
async def msg_admin_refund_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    refund_id = data.get("refund_chat_id")
    if not refund_id:
        await state.clear()
        await message.answer("Сессия истекла. /admin")
        return

    body = (message.text or "").strip()
    if not body:
        await message.answer("❌ Пустое сообщение. Введите текст.")
        return
    if body.startswith("/"):
        if body.split("@")[0].lower() == "/admin":
            await state.set_state(None)
            await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
        return

    from bot import bot as tg_bot
    saved = await store_and_deliver_refund_message(
        refund_id=refund_id,
        sender_tg_id=message.from_user.id,
        is_admin=True,
        body=body,
        bot=tg_bot,
    )
    if not saved:
        await state.set_state(None)
        await message.answer("❌ Запрос на возврат уже закрыт.")
        return

    messages = await db.get_refund_messages(refund_id)
    text = format_refund_chat_history(messages, refund_id=refund_id, for_admin=True)
    await message.answer(
        "✅ Сообщение отправлено.\n\n" + text,
        reply_markup=admin_refund_chat_kb(refund_id),
    )


@router.callback_query(F.data.regexp(r"^adm:refund:\d+$"))
async def cb_admin_refund_detail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    refund_id = int(cb.data.split(":")[2])
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row.get("status") != "pending":
        await safe_cb_answer(cb, "Запрос не найден или уже закрыт", show_alert=True)
        return

    label = _user_label(row.get("username"), row.get("first_name"), row["tg_id"])
    msg_count = len(await db.get_refund_messages(refund_id))
    text = (
        "💸 <b>Запрос на возврат</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Запрос: <code>#{refund_id}</code>\n"
        f"Пользователь: {label}\n"
        f"TG ID: <code>{row['tg_id']}</code>\n"
        f"Клиент: <code>{row['client_email']}</code>\n"
        f"Подписка до: <b>{row['end_date'][:10]}</b>\n"
        f"Создан: {row['created_at'][:16]}\n"
        f"💬 Сообщений в переписке: <b>{msg_count}</b>"
    )
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, admin_refund_detail_kb(refund_id))


@router.callback_query(F.data.startswith("adm:refund:close:"))
async def cb_admin_refund_close(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    refund_id = int(cb.data.split(":")[3])
    closed = await db.close_refund_request(refund_id)
    if not closed:
        await safe_cb_answer(cb, "Запрос не найден или уже закрыт", show_alert=True)
        return

    await safe_cb_answer(cb, "Запрос закрыт")
    rows = await db.get_pending_refunds()
    if not rows:
        text = "💸 <b>Запросы на возврат</b>\n\nНет открытых запросов."
        kb = admin_back_kb()
    else:
        text = (
            "✅ <b>Запрос закрыт</b>\n\n"
            "💸 <b>Запросы на возврат</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"Открытых: <b>{len(rows)}</b>\n"
            "Выберите запрос:"
        )
        kb = admin_refunds_kb(rows)
    await send_or_edit(cb, text, kb)


@router.callback_query(F.data == "adm:plans")
async def cb_admin_plans(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    plans = await list_plans()
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_plans_text(plans), admin_plans_kb(plans))


@router.callback_query(F.data.startswith("adm:plan_price:"))
async def cb_admin_plan_price(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    plan_id = cb.data.split(":", 2)[2]
    plan = get_plan(plan_id)
    if not plan:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    await state.set_state(AdminPricingStates.waiting_plan_price)
    await state.update_data(edit_plan_id=plan_id)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"✏️ <b>Цена: {plan['name']}</b>\n\n"
        f"Дефолт в config: <code>{plan['price']} ₽</code>\n\n"
        "Отправьте новую цену в рублях (целое число).\n"
        "Для отмены: /admin",
        admin_back_kb(),
    )


@router.message(AdminPricingStates.waiting_plan_price)
async def msg_set_plan_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    plan_id = data.get("edit_plan_id")
    if not plan_id:
        await state.clear()
        await message.answer("Сессия истекла. /admin")
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Введите целое число, например: 350")
        return
    price = int(raw)
    try:
        await set_plan_price(plan_id, price)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    await state.clear()
    plan = get_plan(plan_id)
    await message.answer(
        f"✅ Цена <b>{plan['name']}</b> обновлена: <b>{price} ₽</b>",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data == "adm:promos")
async def cb_admin_promos(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    promos = await promo_db.list_promo_codes()
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_promos_text(promos), admin_promos_kb(promos))


@router.callback_query(F.data == "adm:promo:create")
async def cb_admin_promo_create(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminPricingStates.waiting_promo_code)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "➕ <b>Новый промокод</b>\n\n"
        "Шаг 1/5. Отправьте код (латиница/цифры).\n"
        "Пример: <code>SALE20</code>\n\n"
        "Для отмены: /admin",
        admin_back_kb(),
    )


@router.message(AdminPricingStates.waiting_promo_code)
async def msg_promo_code_step(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{3,32}", code):
        await message.answer("❌ Код: 3–32 символа, латиница, цифры, _ -")
        return
    if await promo_db.get_promo_by_code(code):
        await message.answer("❌ Такой промокод уже есть.")
        return
    await state.update_data(new_promo_code=code)
    await state.set_state(AdminPricingStates.waiting_promo_discount)
    await message.answer(
        f"Шаг 2/5. Скидка для <code>{code}</code>:\n"
        "• <code>20%</code> — процент\n"
        "• <code>100</code> — 100 ₽ фиксированно"
    )


@router.message(AdminPricingStates.waiting_promo_discount)
async def msg_promo_discount_step(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip().replace(" ", "")
    discount_type = None
    discount_value = None
    if raw.endswith("%"):
        try:
            discount_value = int(raw[:-1])
            discount_type = "percent"
        except ValueError:
            pass
    elif raw.isdigit():
        discount_value = int(raw)
        discount_type = "fixed"
    if not discount_type or discount_value <= 0:
        await message.answer("❌ Формат: 20% или 100")
        return
    if discount_type == "percent" and discount_value > 100:
        await message.answer("❌ Процент не больше 100")
        return
    await state.update_data(
        new_promo_discount_type=discount_type,
        new_promo_discount_value=discount_value,
    )
    await state.set_state(AdminPricingStates.waiting_promo_max_uses)
    await message.answer(
        "Шаг 3/5. Общий лимит (все пользователи).\n"
        "• <code>0</code> — безлимит\n"
        "• <code>50</code> — не больше 50 раз всего"
    )


@router.message(AdminPricingStates.waiting_promo_max_uses)
async def msg_promo_max_uses_step(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Введите число, например 0 или 100")
        return
    max_uses = int(raw)
    await state.update_data(new_promo_max_uses=None if max_uses == 0 else max_uses)
    await state.set_state(AdminPricingStates.waiting_promo_per_user)
    await message.answer(
        "Шаг 4/5. Лимит на одного пользователя.\n"
        "• <code>1</code> — один раз на человека\n"
        "• <code>3</code> — каждый может применить до 3 раз\n"
        "• <code>0</code> — безлимит на пользователя"
    )


@router.message(AdminPricingStates.waiting_promo_per_user)
async def msg_promo_per_user_step(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Введите число, например 1 или 0")
        return
    per_user = int(raw)
    await state.update_data(new_promo_per_user=per_user)
    await state.set_state(AdminPricingStates.waiting_promo_valid_days)
    await message.answer(
        "Шаг 5/5. Срок действия в днях.\n"
        "• <code>0</code> — без срока\n"
        "• <code>30</code> — 30 дней"
    )


@router.message(AdminPricingStates.waiting_promo_valid_days)
async def msg_promo_valid_days_step(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("❌ Введите число дней, например 0 или 30")
        return
    valid_days = int(raw)
    data = await state.get_data()
    try:
        promo = await promo_db.create_promo_code(
            code=data["new_promo_code"],
            discount_type=data["new_promo_discount_type"],
            discount_value=data["new_promo_discount_value"],
            max_uses=data.get("new_promo_max_uses"),
            per_user_limit=data.get("new_promo_per_user", 1),
            valid_days=valid_days or None,
        )
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    await state.clear()
    await message.answer(
        admin_promo_detail_text(promo) + "\n\n✅ Промокод создан!",
        reply_markup=admin_promo_detail_kb(promo["id"], is_active=True),
    )


@router.callback_query(F.data.regexp(r"^adm:promo:\d+$"))
async def cb_admin_promo_detail(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    promo_id = int(cb.data.split(":")[2])
    promo = await promo_db.get_promo_by_id(promo_id)
    if not promo:
        await safe_cb_answer(cb, "Промокод не найден", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_promo_detail_text(promo),
        admin_promo_detail_kb(promo_id, is_active=bool(promo.get("is_active"))),
    )


@router.callback_query(F.data.startswith("adm:promo:toggle:"))
async def cb_admin_promo_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    promo_id = int(cb.data.split(":")[3])
    promo = await promo_db.get_promo_by_id(promo_id)
    if not promo:
        await safe_cb_answer(cb, "Не найден", show_alert=True)
        return
    new_state = not bool(promo.get("is_active"))
    await promo_db.set_promo_active(promo_id, new_state)
    promo = await promo_db.get_promo_by_id(promo_id)
    await safe_cb_answer(cb, "Включён" if new_state else "Отключён")
    await send_or_edit(
        cb,
        admin_promo_detail_text(promo),
        admin_promo_detail_kb(promo_id, is_active=new_state),
    )


@router.callback_query(F.data.startswith("adm:promo:del:"))
async def cb_admin_promo_delete(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    promo_id = int(cb.data.split(":")[3])
    deleted = await promo_db.delete_promo_code(promo_id)
    if not deleted:
        await safe_cb_answer(cb, "Не найден", show_alert=True)
        return
    promos = await promo_db.list_promo_codes()
    await safe_cb_answer(cb, "Удалён")
    await send_or_edit(cb, admin_promos_text(promos), admin_promos_kb(promos))


@router.callback_query(F.data == "adm:trial")
async def cb_admin_trial_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    grants = await trial_db.list_recent_trial_grants()
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_trial_menu_text(grants), admin_trial_kb(grants))


@router.callback_query(F.data == "adm:trial:search")
async def cb_admin_trial_search(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_trial_reset)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🔍 <b>Сброс пробного периода</b>\n\n"
        "Отправьте TG ID пользователя.\n"
        "Для отмены: /admin",
        admin_back_kb(),
    )


@router.message(AdminStates.waiting_trial_reset)
async def msg_admin_trial_reset_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите числовой TG ID.")
        return
    tg_id = int(raw)
    await state.set_state(None)
    user = await db.get_or_create_user(tg_id)
    label = _user_label(user.get("username"), user.get("first_name"), tg_id)
    await message.answer(
        admin_trial_reset_confirm_text(tg_id, label),
        reply_markup=admin_trial_reset_confirm_kb(tg_id),
    )


@router.callback_query(F.data.startswith("adm:trial_reset:") & ~F.data.startswith("adm:trial_reset:confirm:"))
async def cb_admin_trial_reset_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    tg_id = int(cb.data.split(":")[2])
    user = await db.get_or_create_user(tg_id)
    label = _user_label(user.get("username"), user.get("first_name"), tg_id)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_trial_reset_confirm_text(tg_id, label),
        admin_trial_reset_confirm_kb(tg_id),
    )


@router.callback_query(F.data.startswith("adm:trial_reset:confirm:"))
async def cb_admin_trial_reset(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    tg_id = int(cb.data.split(":")[3])
    await safe_cb_answer(cb, "Сбрасываем…")
    await send_or_edit(cb, "⏳ Сброс пробного периода…")
    try:
        result = await admin_reset_trial(tg_id)
    except Exception as e:
        logger.exception("Trial reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    removed = result.get("removed_trials") or []
    removed_text = ", ".join(t["email"] for t in removed) if removed else "—"
    text = (
        "✅ <b>Пробный период сброшен</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"TG ID: <code>{tg_id}</code>\n"
        f"Удалено записей о выдаче: <b>{result['grants_deleted']}</b>\n"
        f"Снято с панели: {removed_text}\n\n"
        "Пользователь может снова взять пробный период."
    )
    await send_or_edit(cb, text, admin_trial_kb(await trial_db.list_recent_trial_grants()))
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
from db.promo_codes import PROMO_TYPE_GRANT
from db.plan_prices import set_plan_price
from services.pricing import list_plans
from config.plans import get_plan
from db import trial_grants as trial_db
from .messages import (
    admin_plans_text,
    admin_promos_text,
    admin_promo_detail_text,
    admin_trial_menu_text,
    admin_trial_reset_all_confirm_text,
    admin_trial_reset_confirm_text,
)
from config.trial import is_trial_email
from services.trial import admin_reset_all_trial_subscriptions, admin_reset_trial
from .states import AdminPricingStates, AdminStates
from services.subscription_admin import admin_delete_subscription
from services.process_stats import fetch_bot_load_block
from .admin_users import (
    admin_user_subs_text,
    admin_users_category_text,
    admin_users_menu_text,
    admin_users_search_text,
    group_subscriptions_by_tg,
    subscription_kind_label,
    unique_tg_users_from_subs,
)
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_menu_kb,
    admin_back_kb,
    admin_plans_kb,
    admin_promos_kb,
    admin_promo_detail_kb,
    admin_promo_type_kb,
    admin_promo_grant_plans_kb,
    admin_users_kb,
    admin_users_menu_kb,
    admin_users_search_kb,
    admin_user_subs_kb,
    admin_user_detail_kb,
    admin_delete_confirm_kb,
    admin_trial_kb,
    admin_trial_reset_all_confirm_kb,
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


def _admin_stats_block(stats: dict[str, int], *, usage_line: str = "") -> str:
    lines = [
        f"👥 Пользователей: <b>{stats['users']}</b>",
        f"✅ Платных подписок: <b>{stats['paid_subs']}</b>",
        f"🎁 Пробных подписок: <b>{stats['trial_subs']}</b>",
        f"💰 Оплаченных заказов: <b>{stats['paid_orders']}</b>",
        (
            f"🎫 Открытых тикетов: <b>{stats['pending_tickets']}</b> "
            f"(💸 {stats['pending_refunds']} · 🛠 {stats['pending_support']} · "
            f"📁 {stats['pending_other']})"
        ),
    ]
    if usage_line:
        lines.append(usage_line)
    return "\n".join(lines)


async def _admin_menu_context() -> tuple[dict[str, int], str]:
    orphans = await db.deactivate_orphan_subscriptions()
    if orphans:
        logger.info("Admin menu: deactivated {} orphan subscription(s)", orphans)
    stats = await db.get_admin_stats()
    usage_line = await fetch_bot_load_block()
    summary = await nodes_db.nodes_summary()
    primary = await nodes_db.get_primary_node()
    primary_name = primary["name"] if primary else "—"
    primary_inbounds = primary.get("inbound_ids") if primary else "—"
    nodes_line = (
        f"🖧 Ноды: <b>{summary['total']}</b> "
        f"(healthy <b>{summary['healthy']}</b>/<b>{summary['enabled']}</b>)"
    )
    text = (
        "🛠 <b>Админ-панель</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{_admin_stats_block(stats, usage_line=usage_line)}\n\n"
        f"{nodes_line}\n"
        f"★ Основная: <b>{primary_name}</b> · inbounds: <code>{primary_inbounds or '—'}</code>\n"
        f"Группа 3x-ui: <code>{settings.XUI_CLIENT_GROUP}</code>\n\n"
        "<i>Выберите раздел ниже</i>"
    )
    return stats, text


async def _admin_menu_text() -> str:
    _, text = await _admin_menu_context()
    return text


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await state.set_state(None)
    stats, text = await _admin_menu_context()
    await message.answer(
        text,
        reply_markup=admin_menu_kb(pending_tickets=stats.get("pending_tickets", 0)),
    )


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    stats, text = await _admin_menu_context()
    await send_or_edit(
        cb,
        text,
        admin_menu_kb(pending_tickets=stats.get("pending_tickets", 0)),
    )


@router.callback_query(F.data == "adm:stats")
async def cb_admin_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    stats = await db.get_admin_stats()
    usage_line = await fetch_bot_load_block()
    summary = await nodes_db.nodes_summary()
    primary = await nodes_db.get_primary_node()
    text = (
        "📊 <b>Статистика</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{_admin_stats_block(stats, usage_line=usage_line)}\n\n"
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
    await state.update_data(
        admin_user_from_search=False,
        admin_user_category=None,
        admin_user_picker_tg_id=None,
    )
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
    users = await db.get_connected_tg_users(_USERS_LIST_LIMIT, trial_only=trial_only)
    await state.update_data(
        admin_user_from_search=False,
        admin_user_category=category,
        admin_user_picker_tg_id=None,
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
    await state.update_data(admin_user_picker_tg_id=None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🔍 <b>Поиск клиента</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте:\n"
        "• <code>@username</code> или <code>username</code>\n"
        "• <code>123456789</code> — Telegram ID\n"
        "• <code>tg123456789</code> — платный клиент\n"
        "• <code>tg123456789_2</code> — вторая подписка\n"
        "• <code>tgfree123456789</code> — пробный клиент\n\n"
        "Для отмены: /admin",
        admin_back_kb(),
    )


async def _show_admin_user_sub_detail(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    sub_id: int,
    from_search: bool = False,
    from_picker: bool = False,
) -> None:
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        if isinstance(target, CallbackQuery):
            await safe_cb_answer(target, "Подписка не найдена", show_alert=True)
        else:
            await target.answer("❌ Подписка не найдена.")
        return

    user = await db.get_or_create_user(sub["tg_id"])
    label = _user_label(user.get("username"), user.get("first_name"), sub["tg_id"])
    kind = subscription_kind_label(sub.get("client_email"))
    display = (sub.get("display_name") or "").strip()
    name_line = f"Название: <b>{display}</b>\n" if display else ""
    text = (
        "👤 <b>Подписка клиента</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Тип: {kind}\n"
        f"Имя: {label}\n"
        f"TG ID: <code>{sub['tg_id']}</code>\n"
        f"{name_line}"
        f"Подписка: <code>#{sub_id}</code>\n"
        f"Клиент: <code>{sub['client_email']}</code>\n"
        f"До: <b>{sub['end_date'][:10]}</b>\n"
        f"subId: <code>{sub.get('sub_id') or '—'}</code>"
    )
    category = (await state.get_data()).get("admin_user_category")
    kb = admin_user_detail_kb(
        sub_id,
        sub["tg_id"],
        from_search=from_search,
        category=category,
        from_picker=from_picker,
    )
    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _show_admin_user_subs_picker(
    target: Message | CallbackQuery,
    state: FSMContext,
    tg_id: int,
    *,
    subs: list | None = None,
    from_search: bool = False,
) -> None:
    data = await state.get_data()
    category = data.get("admin_user_category")
    trial_only = category == "trial" if category in ("paid", "trial") else None
    if subs is None:
        subs = await db.get_active_subscriptions_for_tg(tg_id, trial_only=trial_only)
    if not subs:
        if isinstance(target, CallbackQuery):
            await safe_cb_answer(target, "Активных подписок нет", show_alert=True)
        else:
            await target.answer("❌ У клиента нет активных подписок.")
        return

    if len(subs) == 1:
        await _show_admin_user_sub_detail(
            target,
            state,
            sub_id=subs[0]["subscription_id"],
            from_search=from_search,
            from_picker=False,
        )
        return

    await state.update_data(admin_user_picker_tg_id=tg_id)
    user = await db.get_or_create_user(tg_id)
    label = _user_label(user.get("username"), user.get("first_name"), tg_id)
    text = admin_user_subs_text(label=label, tg_id=tg_id, subs=subs)
    kb = admin_user_subs_kb(
        tg_id,
        subs,
        from_search=from_search,
        category=category,
    )
    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(AdminStates.waiting_user_search)
async def msg_admin_user_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("❌ Введите @username, TG ID или email.")
        return

    subs = await db.search_connected_users(query, limit=50)
    await state.set_state(None)
    await state.update_data(admin_user_from_search=True, admin_user_category=None)

    if not subs:
        await message.answer(
            f"🔍 По запросу <code>{query}</code> активных клиентов не найдено.",
            reply_markup=admin_users_search_kb([]),
        )
        return

    unique_users = unique_tg_users_from_subs(subs)
    if len(unique_users) == 1:
        tg_id = unique_users[0]["tg_id"]
        user_subs = group_subscriptions_by_tg(subs)[tg_id]
        await _show_admin_user_subs_picker(
            message,
            state,
            tg_id,
            subs=user_subs,
            from_search=True,
        )
        return

    await message.answer(
        admin_users_search_text(query, unique_users),
        reply_markup=admin_users_search_kb(unique_users),
    )


@router.callback_query(F.data.regexp(r"^adm:tg:\d+$"))
async def cb_admin_tg_user(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    tg_id = int(cb.data.split(":")[2])
    data = await state.get_data()
    from_search = bool(data.get("admin_user_from_search"))
    await _show_admin_user_subs_picker(cb, state, tg_id, from_search=from_search)


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
    data = await state.get_data()
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return
    from_picker = data.get("admin_user_picker_tg_id") == sub["tg_id"]
    await _show_admin_user_sub_detail(
        cb,
        state,
        sub_id=sub_id,
        from_search=from_search,
        from_picker=from_picker,
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
        import asyncio
        result = await asyncio.wait_for(admin_delete_subscription(sub_id), timeout=90)
    except asyncio.TimeoutError:
        await send_or_edit(
            cb,
            "❌ Таймаут удаления (90 с). Проверьте логи и панель.",
            admin_back_kb(),
        )
        return
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

    text = (
        "✅ <b>Подписка удалена</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Клиент: <code>{result['email']}</code>\n"
        f"TG ID: <code>{result['tg_id']}</code>\n\n"
        "Клиент полностью удалён с панелей."
    )
    await send_or_edit(cb, text, admin_back_kb())


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
        "Шаг 1. Отправьте код (латиница/цифры).\n"
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
    await message.answer(
        f"Шаг 2. Тип промокода <code>{code}</code>:",
        reply_markup=admin_promo_type_kb(),
    )


@router.callback_query(F.data == "adm:promo:type:discount")
async def cb_admin_promo_type_discount(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    data = await state.get_data()
    code = data.get("new_promo_code")
    if not code:
        await safe_cb_answer(cb, "Сессия истекла", show_alert=True)
        return
    await state.update_data(new_promo_type="discount")
    await state.set_state(AdminPricingStates.waiting_promo_discount)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"Шаг 3. Скидка для <code>{code}</code>:\n"
        "• <code>20%</code> — процент\n"
        "• <code>100</code> — 100 ₽ фиксированно",
        admin_back_kb(),
    )


@router.callback_query(F.data == "adm:promo:type:grant")
async def cb_admin_promo_type_grant(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    data = await state.get_data()
    code = data.get("new_promo_code")
    if not code:
        await safe_cb_answer(cb, "Сессия истекла", show_alert=True)
        return
    plans = await list_plans()
    await state.update_data(new_promo_type=PROMO_TYPE_GRANT)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"Шаг 3. Выберите тариф для <code>{code}</code>:\n"
        "Пользователь получит его бесплатно при активации промокода.",
        admin_promo_grant_plans_kb(plans),
    )


@router.callback_query(F.data.startswith("adm:promo:grant_plan:"))
async def cb_admin_promo_grant_plan(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    plan_id = cb.data.split(":", 3)[3]
    if not get_plan(plan_id):
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    await state.update_data(new_promo_grant_plan_id=plan_id)
    await state.set_state(AdminPricingStates.waiting_promo_max_uses)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"Шаг 4. Общий лимит для тарифа <code>{plan_id}</code>.\n"
        "• <code>0</code> — безлимит\n"
        "• <code>50</code> — не больше 50 активаций всего",
        admin_back_kb(),
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
        "Шаг 4. Общий лимит (все пользователи).\n"
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
        "Шаг 5. Лимит на одного пользователя.\n"
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
        "Шаг 6. Срок действия в днях.\n"
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
    promo_type = data.get("new_promo_type", "discount")
    try:
        if promo_type == PROMO_TYPE_GRANT:
            promo = await promo_db.create_promo_code(
                code=data["new_promo_code"],
                discount_type="grant",
                discount_value=0,
                max_uses=data.get("new_promo_max_uses"),
                per_user_limit=data.get("new_promo_per_user", 1),
                valid_days=valid_days or None,
                plan_ids=[data["new_promo_grant_plan_id"]],
                promo_type=PROMO_TYPE_GRANT,
            )
        else:
            promo = await promo_db.create_promo_code(
                code=data["new_promo_code"],
                discount_type=data["new_promo_discount_type"],
                discount_value=data["new_promo_discount_value"],
                max_uses=data.get("new_promo_max_uses"),
                per_user_limit=data.get("new_promo_per_user", 1),
                valid_days=valid_days or None,
                promo_type="discount",
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


async def _active_trial_count() -> int:
    return await db.count_active_trial_subscriptions()


@router.callback_query(F.data == "adm:trial")
async def cb_admin_trial_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    grants = await trial_db.list_recent_trial_grants()
    trial_count = await _active_trial_count()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_trial_menu_text(grants),
        admin_trial_kb(grants, trial_count=trial_count),
    )


@router.callback_query(F.data == "adm:trial:reset_all")
async def cb_admin_trial_reset_all_confirm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    trial_count = await _active_trial_count()
    grants_count = await trial_db.count_trial_grants()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_trial_reset_all_confirm_text(
            trial_count=trial_count,
            grants_count=grants_count,
        ),
        admin_trial_reset_all_confirm_kb(),
    )


@router.callback_query(F.data == "adm:trial:reset_all:confirm")
async def cb_admin_trial_reset_all(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb, "Сбрасываем все пробные…")
    await send_or_edit(cb, "⏳ Сброс всех пробных подписок…")
    try:
        result = await admin_reset_all_trial_subscriptions()
    except Exception as e:
        logger.exception("Bulk trial reset error: {}", e)
        await send_or_edit(
            cb,
            f"❌ Ошибка: <code>{str(e)[:120]}</code>",
            admin_back_kb(),
        )
        return

    removed = result.get("removed_trials") or []
    errors = result.get("errors") or []
    text = (
        "✅ <b>Сброс всех пробных завершён</b>\n\n"
        f"Снято подписок: <b>{len(removed)}</b>\n"
        f"Сброшено лимитов (grants): <b>{result.get('grants_deleted', 0)}</b>\n"
        f"Ошибок: <b>{len(errors)}</b>"
    )
    if errors:
        text += "\n\n" + "\n".join(
            f"• #{e.get('subscription_id')} <code>{e.get('email')}</code>"
            for e in errors[:5]
        )
    grants = await trial_db.list_recent_trial_grants()
    await send_or_edit(cb, text, admin_trial_kb(grants, trial_count=0))


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
    await send_or_edit(
        cb, text,
        admin_trial_kb(
            await trial_db.list_recent_trial_grants(),
            trial_count=await _active_trial_count(),
        ),
    )
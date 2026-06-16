from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.trial import is_trial_email


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="💰 Цены тарифов", callback_data="adm:plans")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="adm:promos")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users")],
        [InlineKeyboardButton(text="💸 Запросы на возврат", callback_data="adm:refunds")],
        [InlineKeyboardButton(text="🖧 Ноды", callback_data="adm:nodes")],
        [InlineKeyboardButton(text="📡 Inbounds подписки", callback_data="adm:inbounds")],
        [InlineKeyboardButton(text="🎁 Пробный период", callback_data="adm:trial")],
    ])


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_inbounds_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить инбаунды", callback_data="adm:inbounds:edit")],
        [InlineKeyboardButton(text="« Назад", callback_data="adm:menu")],
    ])


def admin_users_menu_kb(*, paid_count: int, trial_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Платные ({paid_count})",
            callback_data="adm:users:paid",
        )],
        [InlineKeyboardButton(
            text=f"🎁 Пробные ({trial_count})",
            callback_data="adm:users:trial",
        )],
        [InlineKeyboardButton(text="🔍 Поиск по @user или TG ID", callback_data="adm:users:search")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def _admin_user_button_label(u: dict) -> str:
    label = u.get("username") or u.get("first_name") or str(u["tg_id"])
    if len(label) > 18:
        label = label[:15] + "..."
    kind = "🎁" if is_trial_email(u.get("client_email")) else "✅"
    end = (u.get("end_date") or "")[:10]
    return f"{kind} {label} · {end}"


def admin_users_kb(
    users: list,
    *,
    category: str | None = None,
    from_search: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not from_search and category is None:
        rows.append([InlineKeyboardButton(
            text="🔍 Поиск по @user или TG ID",
            callback_data="adm:users:search",
        )])
    for u in users:
        rows.append([InlineKeyboardButton(
            text=_admin_user_button_label(u),
            callback_data=f"adm:user:{u['subscription_id']}",
        )])
    back = "adm:users:search" if from_search else "adm:users"
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_search_kb(paid: list, trial: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in (paid, trial):
        for u in group:
            rows.append([InlineKeyboardButton(
                text=_admin_user_button_label(u),
                callback_data=f"adm:user:{u['subscription_id']}",
            )])
    rows.append([InlineKeyboardButton(text="🔍 Новый поиск", callback_data="adm:users:search")])
    rows.append([InlineKeyboardButton(text="« К категориям", callback_data="adm:users")])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_detail_kb(
    subscription_id: int,
    tg_id: int,
    *,
    from_search: bool = False,
    category: str | None = None,
) -> InlineKeyboardMarkup:
    if from_search:
        back = "adm:users:search"
    elif category == "paid":
        back = "adm:users:paid"
    elif category == "trial":
        back = "adm:users:trial"
    else:
        back = "adm:users"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Сброс пробного",
            callback_data=f"adm:trial_reset:{tg_id}",
        )],
        [InlineKeyboardButton(
            text="🗑 Удалить подписку",
            callback_data=f"adm:del_sub:{subscription_id}",
        )],
        [InlineKeyboardButton(text="« К списку", callback_data=back)],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_delete_confirm_kb(subscription_id: int, *, from_search: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить удаление",
            callback_data=f"adm:del_sub:confirm:{subscription_id}",
        )],
        [InlineKeyboardButton(
            text="« Отмена",
            callback_data=f"adm:user:{subscription_id}:search" if from_search else f"adm:user:{subscription_id}",
        )],
    ])


def admin_refunds_kb(refunds: list) -> InlineKeyboardMarkup:
    rows = []
    for r in refunds:
        label = r.get("username") or r.get("first_name") or str(r["tg_id"])
        if len(label) > 20:
            label = label[:17] + "..."
        rows.append([
            InlineKeyboardButton(
                text=f"💸 #{r['id']} {label}",
                callback_data=f"adm:refund:{r['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_plans_kb(plans: list) -> InlineKeyboardMarkup:
    rows = []
    for p in plans:
        default = p.get("default_price", p["price"])
        changed = " ✏️" if p["price"] != default else ""
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} — {p['price']} ₽{changed}",
            callback_data=f"adm:plan_price:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promos_kb(promos: list) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Создать промокод", callback_data="adm:promo:create")]]
    for p in promos:
        status = "✅" if p.get("is_active") else "⏸"
        label = f"{status} {p['code']}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"adm:promo:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_detail_kb(promo_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    toggle = "⏸ Отключить" if is_active else "✅ Включить"
    toggle_data = f"adm:promo:toggle:{promo_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle, callback_data=toggle_data)],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:promo:del:{promo_id}")],
        [InlineKeyboardButton(text="« К списку", callback_data="adm:promos")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_refund_detail_kb(refund_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💬 Переписка",
            callback_data=f"adm:refund:chat:{refund_id}",
        )],
        [InlineKeyboardButton(
            text="✅ Закрыть запрос",
            callback_data=f"adm:refund:close:{refund_id}",
        )],
        [InlineKeyboardButton(text="« К списку", callback_data="adm:refunds")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_trial_reset_all_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить сброс всех",
            callback_data="adm:trial:reset_all:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:trial")],
    ])


def admin_trial_kb(grants: list, *, trial_count: int = 0) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔍 Сброс по TG ID", callback_data="adm:trial:search")],
    ]
    if trial_count > 0:
        rows.append([InlineKeyboardButton(
            text=f"🗑 Сбросить все пробные ({trial_count})",
            callback_data="adm:trial:reset_all",
        )])
    for g in grants[:8]:
        label = g.get("username") or g.get("first_name") or str(g["tg_id"])
        if len(label) > 16:
            label = label[:13] + "..."
        rows.append([InlineKeyboardButton(
            text=f"🔄 {label}",
            callback_data=f"adm:trial_reset:{g['tg_id']}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_trial_reset_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить сброс",
            callback_data=f"adm:trial_reset:confirm:{tg_id}",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:trial")],
    ])


def admin_refund_chat_kb(refund_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Написать пользователю",
            callback_data=f"adm:refund:reply:{refund_id}",
        )],
        [InlineKeyboardButton(
            text="« К запросу",
            callback_data=f"adm:refund:{refund_id}",
        )],
        [InlineKeyboardButton(text="« К списку", callback_data="adm:refunds")],
    ])
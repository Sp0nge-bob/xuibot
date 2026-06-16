from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def admin_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="💰 Цены тарифов", callback_data="adm:plans")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="adm:promos")],
        [InlineKeyboardButton(text="👥 Подключённые пользователи", callback_data="adm:users")],
        [InlineKeyboardButton(text="💸 Запросы на возврат", callback_data="adm:refunds")],
        [InlineKeyboardButton(text="📡 Инбаунды подписки", callback_data="adm:inbounds")],
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


def admin_users_kb(users: list, *, from_search: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔍 Поиск по @user или TG ID", callback_data="adm:users:search")],
    ]
    for u in users:
        label = u.get("username") or u.get("first_name") or str(u["tg_id"])
        if len(label) > 24:
            label = label[:21] + "..."
        rows.append([
            InlineKeyboardButton(
                text=f"👤 {label}",
                callback_data=f"adm:user:{u['subscription_id']}",
            )
        ])
    back = "adm:users:search" if from_search else "adm:users"
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_detail_kb(subscription_id: int, *, from_search: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🗑 Удалить подписку",
            callback_data=f"adm:del_sub:{subscription_id}",
        )],
        [InlineKeyboardButton(
            text="« К списку",
            callback_data="adm:users:search" if from_search else "adm:users",
        )],
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
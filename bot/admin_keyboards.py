from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.settings import settings
from config.trial import is_trial_email
from .admin_users import subscription_picker_button_label


def admin_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(text="🔍 Диагностика", callback_data="adm:diagnostics")],
        [
            InlineKeyboardButton(text="💰 Тарифы", callback_data="adm:plans"),
            InlineKeyboardButton(text="💳 Оплата", callback_data="adm:payments"),
        ],
        [
            InlineKeyboardButton(text="🎟 Промокоды", callback_data="adm:promos"),
            InlineKeyboardButton(text="🎁 Пробный", callback_data="adm:trial"),
        ],
        [
            InlineKeyboardButton(text="👥 Клиенты", callback_data="adm:users"),
            InlineKeyboardButton(text="🎫 Тикеты", callback_data="adm:tickets"),
        ],
        [
            InlineKeyboardButton(text="🖧 Ноды", callback_data="adm:nodes"),
            InlineKeyboardButton(text="📡 Inbounds", callback_data="adm:inbounds"),
        ],
        [InlineKeyboardButton(text="🌐 Доступность серверов", callback_data="adm:server_status")],
        [
            InlineKeyboardButton(text="❓ FAQ", callback_data="adm:faq"),
            InlineKeyboardButton(text="🔐 Happ", callback_data="adm:happ_crypto"),
        ],
        [
            InlineKeyboardButton(text="📱 Лимит IP", callback_data="adm:limit_ip"),
        ],
        [
            InlineKeyboardButton(text="📢 /start", callback_data="adm:start_text"),
            InlineKeyboardButton(text="📄 Документы", callback_data="adm:legal"),
        ],
        [InlineKeyboardButton(text="💾 Бэкап", callback_data="adm:backup")],
    ]
    if settings.ALLOW_DEBUG_ADMIN:
        rows.append([InlineKeyboardButton(text="🧪 Отладка", callback_data="adm:debug")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_legal_kb(
    *,
    privacy_custom: bool = False,
    terms_custom: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text="🔒 Политика конфиденциальности",
            callback_data="adm:legal:edit:privacy",
        )],
        [InlineKeyboardButton(
            text="📜 Пользовательское соглашение",
            callback_data="adm:legal:edit:terms",
        )],
    ]
    if privacy_custom:
        rows.append([InlineKeyboardButton(
            text="↩️ Сбросить политику (дефолт)",
            callback_data="adm:legal:reset:privacy",
        )])
    if terms_custom:
        rows.append([InlineKeyboardButton(
            text="↩️ Сбросить соглашение (дефолт)",
            callback_data="adm:legal:reset:terms",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_start_text_kb(
    *,
    has_greeting: bool = False,
    has_announcement: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text="👋 Изменить приветствие",
            callback_data="adm:start_text:greeting:edit",
        )],
    ]
    if has_greeting:
        rows.append([InlineKeyboardButton(
            text="↩️ Сбросить приветствие",
            callback_data="adm:start_text:greeting:clear",
        )])
    rows.append([InlineKeyboardButton(
        text="✏️ Изменить блок новостей",
        callback_data="adm:start_text:edit",
    )])
    if has_announcement:
        rows.append([InlineKeyboardButton(
            text="🗑 Очистить блок новостей",
            callback_data="adm:start_text:clear",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_start_text_clear_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Да, очистить",
            callback_data="adm:start_text:clear:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:start_text")],
    ])


def _faq_admin_title(title: str, *, max_len: int = 36) -> str:
    t = (title or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def admin_faq_menu_kb(articles: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Новая статья", callback_data="adm:faq:create")],
    ]
    for a in articles:
        status = "✅" if a.get("is_published") else "⏸"
        rows.append([InlineKeyboardButton(
            text=f"{status} {_faq_admin_title(a.get('title') or '')}",
            callback_data=f"adm:faq:{a['id']}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_faq_detail_kb(
    article_id: int,
    *,
    is_published: bool,
    is_builtin: bool = False,
) -> InlineKeyboardMarkup:
    toggle = "⏸ Скрыть" if is_published else "✅ Опубликовать"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✏️ Заголовок", callback_data=f"adm:faq:{article_id}:title"),
            InlineKeyboardButton(text="📝 Текст", callback_data=f"adm:faq:{article_id}:body"),
        ],
    ]
    if not is_builtin:
        rows.append([
            InlineKeyboardButton(text="🖼 Добавить фото", callback_data=f"adm:faq:{article_id}:photos"),
            InlineKeyboardButton(text="👁 Превью", callback_data=f"adm:faq:{article_id}:preview"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="👁 Превью", callback_data=f"adm:faq:{article_id}:preview"),
        ])
    rows.append([InlineKeyboardButton(text=toggle, callback_data=f"adm:faq:{article_id}:toggle")])
    if not is_builtin:
        rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:faq:{article_id}:del")])
    rows.append([
        InlineKeyboardButton(text="« К FAQ", callback_data="adm:faq"),
        InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_faq_photos_kb(*, create_mode: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="✅ Готово", callback_data="adm:faq:photos:done"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="adm:faq:photos:skip"),
        ],
    ]
    if not create_mode:
        rows.append([InlineKeyboardButton(text="« Отмена", callback_data="adm:faq:photos:cancel")])
    else:
        rows.append([InlineKeyboardButton(text="« Отмена", callback_data="adm:faq")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_faq_delete_confirm_kb(article_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Да, удалить",
            callback_data=f"adm:faq:{article_id}:del:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data=f"adm:faq:{article_id}")],
    ])


def admin_faq_photos_manage_kb(article_id: int, photos: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in photos:
        rows.append([InlineKeyboardButton(
            text=f"🗑 Удалить фото #{p['id']}",
            callback_data=f"adm:faq:{article_id}:photo_del:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text="🖼 Добавить ещё",
        callback_data=f"adm:faq:{article_id}:photos",
    )])
    rows.append([InlineKeyboardButton(text="« К статье", callback_data=f"adm:faq:{article_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_backup_kb(
    *,
    backup_enabled: bool = True,
    env_disabled: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📤 Отправить бэкап сейчас", callback_data="adm:backup:now")],
    ]
    if not env_disabled:
        toggle_label = (
            "⏸ Выключить ежедневный бэкап"
            if backup_enabled
            else "▶️ Включить ежедневный бэкап"
        )
        rows.append([InlineKeyboardButton(text=toggle_label, callback_data="adm:backup:toggle")])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_debug_entry_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, войти в отладку",
            callback_data="adm:debug:enter",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:menu")],
    ])


def admin_debug_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑 Пробные",
                callback_data="adm:trial:reset_all",
            ),
            InlineKeyboardButton(
                text="🎟 Промокоды",
                callback_data="adm:debug:promos_reset",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🧾 Заказы",
                callback_data="adm:debug:orders_reset",
            ),
            InlineKeyboardButton(
                text="🎫 Тикеты",
                callback_data="adm:debug:tickets_reset",
            ),
        ],
        [InlineKeyboardButton(
            text="👥 Пользователи",
            callback_data="adm:debug:users_reset",
        )],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_debug_users_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить удаление",
            callback_data="adm:debug:users_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_tickets_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить удаление",
            callback_data="adm:debug:tickets_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_orders_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить удаление",
            callback_data="adm:debug:orders_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_promo_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить очистку",
            callback_data="adm:debug:promos_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_happ_crypto_kb(mode: str) -> InlineKeyboardMarkup:
    from config.happ_crypto import HAPP_CRYPTO_MODES, HAPP_CRYPTO_MODE_LABELS

    rows: list[list[InlineKeyboardButton]] = []
    icons = {
        "none": "🔓",
        "crypt3_local": "🔑",
        "crypt5_api": "🌐",
    }
    for key in HAPP_CRYPTO_MODES:
        prefix = "✅ " if key == mode else ""
        icon = icons.get(key, "")
        label = HAPP_CRYPTO_MODE_LABELS.get(key, key)
        rows.append([InlineKeyboardButton(
            text=f"{prefix}{icon} {label}",
            callback_data=f"adm:happ_crypto:set:{key}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_limit_ip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Пробная", callback_data="adm:limit_ip:edit:trial")],
        [InlineKeyboardButton(text="✅ Платная", callback_data="adm:limit_ip:edit:paid")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_payment_methods_kb(enabled: dict[str, bool]) -> InlineKeyboardMarkup:
    from config.payments import all_payment_method_definitions

    rows: list[list[InlineKeyboardButton]] = []
    for m in all_payment_method_definitions():
        is_on = enabled.get(m["key"], False)
        status = "✅" if is_on else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{status} {m['emoji']} {m['name']}",
            callback_data=f"adm:payments:toggle:{m['key']}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_server_status_kb(nodes: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for node in nodes:
        nid = node["id"]
        available = bool(int(node.get("public_available", 1)))
        icon = "🟢" if available else "🔴"
        star = "★ " if node.get("is_primary") else ""
        name = (node.get("name") or f"#{nid}").strip()
        if len(name) > 28:
            name = name[:25] + "…"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {star}{name}",
            callback_data=f"adm:server_status:toggle:{nid}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_inbounds_kb(*, differs_from_env: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="✏️ Изменить инбаунды", callback_data="adm:inbounds:edit")],
    ]
    if differs_from_env:
        rows.append([InlineKeyboardButton(
            text="↩️ Сбросить до .env",
            callback_data="adm:inbounds:reset_env",
        )])
    rows.append([InlineKeyboardButton(text="« Назад", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_menu_kb(*, paid_count: int, trial_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ Платные ({paid_count})",
                callback_data="adm:users:paid",
            ),
            InlineKeyboardButton(
                text=f"🎁 Пробные ({trial_count})",
                callback_data="adm:users:trial",
            ),
        ],
        [InlineKeyboardButton(text="🔍 Поиск @user / TG ID", callback_data="adm:users:search")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def _admin_tg_user_button_label(u: dict) -> str:
    label = u.get("username") or u.get("first_name") or str(u["tg_id"])
    if len(label) > 16:
        label = label[:13] + "..."
    end = (u.get("end_date") or "")[:10]
    sub_count = int(u.get("sub_count") or 1)
    suffix = f" · {sub_count} подп." if sub_count > 1 else f" · {end}"
    return f"👤 {label}{suffix}"


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
            text=_admin_tg_user_button_label(u),
            callback_data=f"adm:tg:{u['tg_id']}",
        )])
    back = "adm:users:search" if from_search else "adm:users"
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back)])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_users_search_kb(users: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for u in users:
        rows.append([InlineKeyboardButton(
            text=_admin_tg_user_button_label(u),
            callback_data=f"adm:tg:{u['tg_id']}",
        )])
    rows.append([InlineKeyboardButton(text="🔍 Новый поиск", callback_data="adm:users:search")])
    rows.append([InlineKeyboardButton(text="« К категориям", callback_data="adm:users")])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_subs_kb(
    tg_id: int,
    subs: list,
    *,
    from_search: bool = False,
    category: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sub in subs:
        rows.append([InlineKeyboardButton(
            text=subscription_picker_button_label(sub),
            callback_data=f"adm:user:{sub['subscription_id']}",
        )])
    if from_search:
        back = "adm:users:search"
    elif category == "paid":
        back = "adm:users:paid"
    elif category == "trial":
        back = "adm:users:trial"
    else:
        back = "adm:users"
    rows.append([InlineKeyboardButton(text="« К списку", callback_data=back)])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_user_detail_kb(
    subscription_id: int,
    tg_id: int,
    *,
    from_search: bool = False,
    category: str | None = None,
    from_picker: bool = False,
) -> InlineKeyboardMarkup:
    if from_picker:
        back = f"adm:tg:{tg_id}"
    elif from_search:
        back = "adm:users:search"
    elif category == "paid":
        back = "adm:users:paid"
    elif category == "trial":
        back = "adm:users:trial"
    else:
        back = "adm:users"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔄 Сброс пробного",
                callback_data=f"adm:trial_reset:{tg_id}",
            ),
            InlineKeyboardButton(
                text="🗑 Удалить",
                callback_data=f"adm:del_sub:{subscription_id}",
            ),
        ],
        [
            InlineKeyboardButton(text="« К списку", callback_data=back),
            InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
        ],
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


def admin_tickets_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все", callback_data="adm:tickets:all")],
        [
            InlineKeyboardButton(text="💸 Возврат", callback_data="adm:tickets:refund"),
            InlineKeyboardButton(text="🛠 Поддержка", callback_data="adm:tickets:support"),
        ],
        [InlineKeyboardButton(text="📁 Другое", callback_data="adm:tickets:other")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_tickets_kb(tickets: list, *, filter_key: str = "all") -> InlineKeyboardMarkup:
    rows = []
    emoji_map = {"refund": "💸", "support": "🛠", "other": "📁"}
    for t in tickets:
        label = t.get("username") or t.get("first_name") or str(t["tg_id"])
        if len(label) > 16:
            label = label[:13] + "..."
        em = emoji_map.get(t.get("category"), "🎫")
        unread = t.get("unread", 0)
        badge = f" ●{unread}" if unread else ""
        order_hint = ""
        if t.get("category") == "refund" and t.get("order_id"):
            order_hint = f" · #{t['order_id']}"
        rows.append([InlineKeyboardButton(
            text=f"{em} #{t['id']}{order_hint} {label}{badge}",
            callback_data=f"adm:ticket:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text="« Фильтры",
        callback_data="adm:tickets",
    )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_detail_kb(ticket_id: int, *, category: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text="💬 Начать переписку по тикету",
            callback_data=f"adm:ticket:session:{ticket_id}",
        )],
    ]
    if category == "refund":
        rows += [
            [InlineKeyboardButton(
                text="✅ Одобрить возврат",
                callback_data=f"adm:ticket:refund_approve:{ticket_id}",
            )],
            [InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"adm:ticket:refund_reject:{ticket_id}",
            )],
        ]
    else:
        rows.append([InlineKeyboardButton(
            text="✅ Закрыть тикет",
            callback_data=f"adm:ticket:close:{ticket_id}",
        )])
    rows += [
        [InlineKeyboardButton(text="« К списку", callback_data="adm:tickets:all")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_ticket_session_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⏹ Завершить переписку",
            callback_data=f"adm:ticket:session_end:{ticket_id}",
        )],
        [InlineKeyboardButton(
            text="« К тикету",
            callback_data=f"adm:ticket:{ticket_id}",
        )],
        [InlineKeyboardButton(text="« К списку", callback_data="adm:tickets:all")],
    ])


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


def admin_promo_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Скидка при оплате", callback_data="adm:promo:type:discount")],
        [InlineKeyboardButton(text="🎁 Бесплатный тариф", callback_data="adm:promo:type:grant")],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:promos")],
    ])


def admin_promo_grant_plans_kb(plans: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"📦 {p['name']} ({p['days']} дн.)",
            callback_data=f"adm:promo:grant_plan:{p['id']}",
        )]
        for p in plans
    ]
    rows.append([InlineKeyboardButton(text="« Отмена", callback_data="adm:promos")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_detail_kb(promo_id: int, *, is_active: bool) -> InlineKeyboardMarkup:
    toggle = "⏸ Выкл" if is_active else "✅ Вкл"
    toggle_data = f"adm:promo:toggle:{promo_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=toggle, callback_data=toggle_data),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:promo:del:{promo_id}"),
        ],
        [
            InlineKeyboardButton(text="« Промокоды", callback_data="adm:promos"),
            InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
        ],
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



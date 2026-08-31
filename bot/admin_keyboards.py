from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config.trial import is_trial_email
from .admin_users import subscription_picker_button_label


def admin_menu_kb(*, pending_tickets: int = 0) -> InlineKeyboardMarkup:
    from .admin_menu import admin_hub_root_kb

    return admin_hub_root_kb(pending_tickets=pending_tickets)


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
    interval: str = "24h",
    interval_overridden: bool = False,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📤 Отправить бэкап сейчас", callback_data="adm:backup:now")],
    ]
    if not env_disabled:
        rows.append([InlineKeyboardButton(
            text=f"⏱ Интервал: {interval}",
            callback_data="adm:backup:interval:edit",
        )])
        toggle_label = (
            "⏸ Выключить автобэкап"
            if backup_enabled
            else "▶️ Включить автобэкап"
        )
        rows.append([InlineKeyboardButton(text=toggle_label, callback_data="adm:backup:toggle")])
        if interval_overridden:
            rows.append([InlineKeyboardButton(
                text="↩️ Интервал из .env",
                callback_data="adm:backup:interval:reset",
            )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_logs_sources_kb(sources: list) -> InlineKeyboardMarkup:
    """Список доступных логов: текущий bot.log + архивы botlog_*."""
    rows: list[list[InlineKeyboardButton]] = []
    for s in sources:
        size = getattr(s, "size_bytes", 0) or 0
        if size < 1024:
            size_s = f"{size}B"
        elif size < 1024 * 1024:
            size_s = f"{size / 1024:.0f}K"
        else:
            size_s = f"{size / (1024 * 1024):.1f}M"
        name = getattr(s, "path").name if getattr(s, "path", None) else s.id
        # Кнопка ≤ ~60 символов; callback: adm:logs:src:active | arch0
        if getattr(s, "is_active", False):
            text = f"🟢 bot.log · {size_s}"
        else:
            short = name.removeprefix("botlog_").removesuffix(".log")
            if len(short) > 22:
                short = short[:21] + "…"
            text = f"📦 {short} · {size_s}"
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"adm:logs:src:{s.id}",
        )])
    rows.append([InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_logs_tail_kb(source_id: str) -> InlineKeyboardMarkup:
    """Пресеты хвоста для выбранного файла + своё число."""
    from services.log_export import LOG_TAIL_PRESETS

    sid = source_id or "active"
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for n in LOG_TAIL_PRESETS:
        pair.append(InlineKeyboardButton(
            text=f"📄 {n}",
            callback_data=f"adm:logs:tail:{sid}:{n}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(
        text="✏️ Своё число строк",
        callback_data=f"adm:logs:custom:{sid}",
    )])
    rows.append([InlineKeyboardButton(
        text="📦 Весь файл",
        callback_data=f"adm:logs:full:{sid}",
    )])
    rows.append([
        InlineKeyboardButton(text="« К списку логов", callback_data="adm:logs"),
        InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_logs_custom_kb(source_id: str = "active") -> InlineKeyboardMarkup:
    sid = source_id or "active"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data=f"adm:logs:src:{sid}")],
    ])


def admin_backup_interval_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:backup")],
    ])


def admin_debug_entry_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Войти", callback_data="adm:debug:enter")],
        [InlineKeyboardButton(text="« Назад", callback_data="adm:menu")],
    ])


def admin_debug_lockdown_kb(
    whitelist: list,
    *,
    enabled: bool = False,
    add_mode: bool = False,
) -> InlineKeyboardMarkup:
    toggle_label = "🔓 Снять" if enabled else "🔒 Включить"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=toggle_label,
                callback_data="adm:debug:lockdown:toggle",
            ),
            InlineKeyboardButton(
                text="➕ ID",
                callback_data="adm:debug:lockdown:add",
            ),
        ],
    ]
    for u in whitelist[:12]:
        tg_id = int(u["tg_id"])
        label = u.get("username") or u.get("first_name") or str(tg_id)
        if len(label) > 14:
            label = label[:11] + "…"
        rows.append([InlineKeyboardButton(
            text=f"🗑 {label}",
            callback_data=f"adm:debug:lockdown:remove:{tg_id}",
        )])
    back_label = "« К блокировке" if add_mode else "« К отладке"
    back_data = "adm:debug:lockdown" if add_mode else "adm:debug:enter"
    rows.append([InlineKeyboardButton(text=back_label, callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_debug_kb(
    *,
    test_mode: bool = False,
    test_mode_overridden: bool = False,
    lockdown_active: bool = False,
) -> InlineKeyboardMarkup:
    test_label = "🧪 Тест: вкл" if test_mode else "🧪 Тест: выкл"
    lock_label = "🔒 Блокировка"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=test_label,
                callback_data="adm:debug:test_mode_toggle",
            ),
            InlineKeyboardButton(
                text=lock_label,
                callback_data="adm:debug:lockdown",
            ),
        ],
    ]
    if test_mode_overridden:
        rows.append([InlineKeyboardButton(
            text="↩️ из .env",
            callback_data="adm:debug:test_mode_reset",
        )])
    rows += [
        [
            InlineKeyboardButton(
                text="📥 С панели",
                callback_data="adm:debug:pull_panel",
            ),
            InlineKeyboardButton(
                text="🔍 Диагностика",
                callback_data="adm:debug:panel_diag",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🧾 Заказы",
                callback_data="adm:debug:orders",
            ),
            InlineKeyboardButton(
                text="🎁 Пробные",
                callback_data="adm:trial",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🎟 Промо",
                callback_data="adm:debug:promos_reset",
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
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_debug_pull_panel_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📥 Подтянуть",
            callback_data="adm:debug:pull_panel:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_users_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить",
            callback_data="adm:debug:users_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_tickets_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить",
            callback_data="adm:debug:tickets_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:enter")],
    ])


def admin_debug_orders_kb(
    *,
    failed_count: int = 0,
    pending_count: int = 0,
) -> InlineKeyboardMarkup:
    failed_label = f"❌ Неудачные · {failed_count}" if failed_count else "❌ Неудачные"
    pending_label = f"⏳ Ожидают · {pending_count}" if pending_count else "⏳ Ожидают"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📋 Оплаченные",
                callback_data="adm:debug:orders:list:paid:0",
            ),
            InlineKeyboardButton(
                text=pending_label,
                callback_data="adm:debug:orders:list:pending:0",
            ),
        ],
        [InlineKeyboardButton(
            text=failed_label,
            callback_data="adm:debug:orders:list:failed:0",
        )],
        [InlineKeyboardButton(
            text="🗑 Сбросить историю",
            callback_data="adm:debug:orders_reset",
        )],
        [InlineKeyboardButton(text="« К отладке", callback_data="adm:debug:enter")],
    ])


def admin_debug_orders_list_kb(
    orders: list,
    *,
    status: str,
    page: int,
    page_size: int,
    total_count: int,
) -> InlineKeyboardMarkup:
    from bot.messages import admin_order_button_label

    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        order_id = int(order["id"])
        rows.append([InlineKeyboardButton(
            text=admin_order_button_label(order),
            callback_data=f"adm:debug:orders:view:{status}:{order_id}:{page}",
        )])
    nav: list[InlineKeyboardButton] = []
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    if page > 0:
        nav.append(InlineKeyboardButton(
            text=f"◀️ Стр. {page}/{total_pages}",
            callback_data=f"adm:debug:orders:list:{status}:{page - 1}",
        ))
    if (page + 1) * page_size < total_count:
        nav.append(InlineKeyboardButton(
            text=f"Стр. {page + 2}/{total_pages} ▶️",
            callback_data=f"adm:debug:orders:list:{status}:{page + 1}",
        ))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="« К заказам", callback_data="adm:debug:orders")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_debug_order_detail_kb(
    *,
    order_id: int,
    status: str,
    page: int,
    can_message: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_message:
        rows.append([InlineKeyboardButton(
            text="💬 Написать клиенту",
            callback_data=f"adm:debug:orders:msg:{status}:{order_id}:{page}",
        )])
    rows += [
        [InlineKeyboardButton(
            text="« К списку",
            callback_data=f"adm:debug:orders:list:{status}:{page}",
        )],
        [InlineKeyboardButton(text="« К заказам", callback_data="adm:debug:orders")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_debug_order_message_kb(
    *,
    order_id: int,
    status: str,
    page: int,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="« К заказу",
            callback_data=f"adm:debug:orders:view:{status}:{order_id}:{page}",
        )],
        [InlineKeyboardButton(text="« К заказам", callback_data="adm:debug:orders")],
    ])


def admin_debug_orders_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить",
            callback_data="adm:debug:orders_reset:confirm",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:debug:orders")],
    ])


def admin_debug_promo_reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚠️ Подтвердить",
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


def admin_payment_methods_kb(
    enabled: dict[str, bool],
    *,
    admin_notify_enabled: bool = True,
) -> InlineKeyboardMarkup:
    from config.payments import all_payment_method_definitions

    notify_flag = "✅" if admin_notify_enabled else "❌"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text=f"{notify_flag} Уведомления об оплатах",
            callback_data="adm:payments:notify_toggle",
        )],
    ]
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


def admin_stats_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:stats:refresh")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_finance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:finance:refresh")],
            [InlineKeyboardButton(text="« Монетизация", callback_data="adm:hub:billing")],
            [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
        ]
    )


def diagnostics_kb(
    *,
    view: str = "summary",
    has_issues: bool = False,
    recs_count: int = 0,
) -> InlineKeyboardMarkup:
    """Клавиатура диагностики: сводка или технический раздел."""
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for label, section in (
        ("🤖 Процессы", "proc"),
        ("🌐 Webhook", "web"),
        ("🖧 VPN", "vpn"),
        ("💾 Хранилище", "store"),
    ):
        text = f"• {label}" if view == section else label
        pair.append(InlineKeyboardButton(
            text=text,
            callback_data=f"adm:diagnostics:{section}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if has_issues and recs_count > 0:
        rec_label = f"📋 Рекомендации ({recs_count})"
        rows.append([InlineKeyboardButton(
            text=rec_label if view != "recs" else f"• {rec_label}",
            callback_data="adm:diagnostics:recs",
        )])

    refresh_cb = (
        f"adm:diagnostics:{view}:refresh"
        if view != "summary"
        else "adm:diagnostics:refresh"
    )
    nav_row: list[InlineKeyboardButton] = [
        InlineKeyboardButton(text="🔄 Обновить", callback_data=refresh_cb),
    ]
    if view != "summary":
        nav_row.append(InlineKeyboardButton(
            text="◀️ Сводка",
            callback_data="adm:diagnostics",
        ))
    rows.append(nav_row)
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
    has_orders: bool = False,
) -> InlineKeyboardMarkup:
    del has_orders  # кнопка чеков всегда — пустой список тоже информативен
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
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            text="🧾 Чеки на эту подписку",
            callback_data=f"adm:sub:orders:{subscription_id}:0",
        )],
        [InlineKeyboardButton(
            text="⏰ Продлить",
            callback_data=f"adm:sub:extend:{subscription_id}",
        )],
    ]
    rows.append([
        InlineKeyboardButton(
            text="🔄 Сброс пробного",
            callback_data=f"adm:trial_reset:{tg_id}",
        ),
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"adm:del_sub:{subscription_id}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(text="« К списку", callback_data=back),
        InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_extend_days_kb(subscription_id: int) -> InlineKeyboardMarkup:
    """Быстрые сроки + своё число дней."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="+7 дн.", callback_data=f"adm:sub:extend_do:{subscription_id}:7"),
                InlineKeyboardButton(text="+30 дн.", callback_data=f"adm:sub:extend_do:{subscription_id}:30"),
            ],
            [
                InlineKeyboardButton(text="+90 дн.", callback_data=f"adm:sub:extend_do:{subscription_id}:90"),
                InlineKeyboardButton(text="✏️ Своё…", callback_data=f"adm:sub:extend_custom:{subscription_id}"),
            ],
            [InlineKeyboardButton(text="« Назад", callback_data=f"adm:user:{subscription_id}")],
        ]
    )


def admin_extend_cancel_kb(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Отмена", callback_data=f"adm:sub:extend:{subscription_id}")],
        ]
    )


def admin_broadcast_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Контент", callback_data="adm:hub:content")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Разослать всем", callback_data="adm:broadcast:send")],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:broadcast")],
    ])


def admin_bulk_days_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+7 дн.", callback_data="adm:bulk_days:pick:7"),
            InlineKeyboardButton(text="+30 дн.", callback_data="adm:bulk_days:pick:30"),
        ],
        [
            InlineKeyboardButton(text="+90 дн.", callback_data="adm:bulk_days:pick:90"),
            InlineKeyboardButton(text="✏️ Своё…", callback_data="adm:bulk_days:custom"),
        ],
        [InlineKeyboardButton(text="« VPN", callback_data="adm:hub:vpn")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


def admin_bulk_days_confirm_kb(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Продлить всех на {days} дн.",
            callback_data=f"adm:bulk_days:do:{days}",
        )],
        [InlineKeyboardButton(text="« Назад", callback_data="adm:bulk_days")],
    ])


def admin_bulk_days_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:bulk_days")],
    ])


def admin_sub_orders_kb(
    subscription_id: int,
    orders: list,
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    from .messages import admin_order_button_label

    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        rows.append([InlineKeyboardButton(
            text=admin_order_button_label(order),
            callback_data=f"adm:sub:order:{subscription_id}:{order['id']}:{page}",
        )])
    nav: list[InlineKeyboardButton] = []
    if has_prev:
        nav.append(InlineKeyboardButton(
            text="‹ Назад",
            callback_data=f"adm:sub:orders:{subscription_id}:{page - 1}",
        ))
    if has_next:
        nav.append(InlineKeyboardButton(
            text="Вперёд ›",
            callback_data=f"adm:sub:orders:{subscription_id}:{page + 1}",
        ))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            text="« К подписке",
            callback_data=f"adm:user:{subscription_id}",
        ),
        InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_sub_order_detail_kb(
    subscription_id: int,
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="« К чекам",
            callback_data=f"adm:sub:orders:{subscription_id}:{page}",
        )],
        [
            InlineKeyboardButton(
                text="« К подписке",
                callback_data=f"adm:user:{subscription_id}",
            ),
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


def admin_promo_edit_grant_plans_kb(promo_id: int, plans: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"📦 {p['name']} ({p['days']} дн.)",
            callback_data=f"adm:promo:edit:grant_plan:{promo_id}:{p['id']}",
        )]
        for p in plans
    ]
    rows.append([InlineKeyboardButton(
        text="« К промокоду",
        callback_data=f"adm:promo:{promo_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_promo_edit_cancel_kb(promo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data=f"adm:promo:{promo_id}")],
    ])


def admin_promo_detail_kb(
    promo_id: int,
    *,
    is_active: bool,
    is_grant: bool = False,
) -> InlineKeyboardMarkup:
    del is_grant  # тип учитывается в подменю редактирования
    toggle = "⏸ Выкл" if is_active else "✅ Вкл"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Редактирование",
            callback_data=f"adm:promo:edit_menu:{promo_id}",
        )],
        [
            InlineKeyboardButton(text=toggle, callback_data=f"adm:promo:toggle:{promo_id}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm:promo:del:{promo_id}"),
        ],
        [
            InlineKeyboardButton(text="« Промокоды", callback_data="adm:promos"),
            InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
        ],
    ])


def admin_promo_edit_menu_kb(
    promo_id: int,
    *,
    is_grant: bool = False,
) -> InlineKeyboardMarkup:
    value_btn = (
        InlineKeyboardButton(
            text="🎁 Тариф grant",
            callback_data=f"adm:promo:edit:grant:{promo_id}",
        )
        if is_grant
        else InlineKeyboardButton(
            text="💰 Скидка",
            callback_data=f"adm:promo:edit:discount:{promo_id}",
        )
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Код", callback_data=f"adm:promo:edit:code:{promo_id}"),
            value_btn,
        ],
        [
            InlineKeyboardButton(
                text="🔢 Лимит всего",
                callback_data=f"adm:promo:edit:max:{promo_id}",
            ),
            InlineKeyboardButton(
                text="👤 На юзера",
                callback_data=f"adm:promo:edit:per_user:{promo_id}",
            ),
        ],
        [InlineKeyboardButton(
            text="📅 Срок действия",
            callback_data=f"adm:promo:edit:valid:{promo_id}",
        )],
        [InlineKeyboardButton(
            text="« К промокоду",
            callback_data=f"adm:promo:{promo_id}",
        )],
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
    rows.append([InlineKeyboardButton(text="« К отладке", callback_data="adm:debug:enter")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_trial_reset_confirm_kb(tg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Подтвердить сброс",
            callback_data=f"adm:trial_reset:confirm:{tg_id}",
        )],
        [InlineKeyboardButton(text="« Отмена", callback_data="adm:trial")],
    ])



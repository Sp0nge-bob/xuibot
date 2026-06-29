from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config.payments import PaymentMethod
from config.plans import Plan
from config.trial import is_trial_email
from services.pricing import PriceQuote
from services.subscription_labels import subscription_short_label

from ui.theme import (
    BTN_BACK,
    BTN_BACK_TARIFFS,
    BTN_CHECK_PAY,
    BTN_HOME,
    BTN_PAY,
    BTN_FAQ,
    BTN_SERVER_STATUS,
    BTN_POLICY,
    BTN_PRIVACY_POLICY,
    BTN_PROMO,
    BTN_REFERRAL,
    BTN_PURCHASE_PROMO,
    BTN_PURCHASE_PLANS,
    BTN_EXIT,
    BTN_RESUME_PAY,
    BTN_SUBSCRIPTION,
    BTN_SUPPORT_SHORT,
    BTN_TARIFFS,
    BTN_TERMS_OF_SERVICE,
    BTN_TRIAL,
    plan_button_label,
)


def nav_row(
    back_callback: str | None = None,
    *,
    back_text: str = BTN_BACK,
) -> list[InlineKeyboardButton]:
    """Единая строка навигации: «Назад» (опционально) + «Главное меню»."""
    buttons: list[InlineKeyboardButton] = []
    if back_callback:
        buttons.append(InlineKeyboardButton(text=back_text, callback_data=back_callback))
    buttons.append(InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu"))
    return buttons


def main_menu_kb(
    *,
    trial_available: bool = False,
    pending_tx_id: str | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if pending_tx_id:
        rows.append([InlineKeyboardButton(
            text=BTN_RESUME_PAY,
            callback_data=f"resume_pay:{pending_tx_id}",
        )])
    if trial_available:
        rows.append([InlineKeyboardButton(text=BTN_TRIAL, callback_data="trial_offer")])
    rows += [
        [
            InlineKeyboardButton(text=BTN_TARIFFS, callback_data="tariffs"),
            InlineKeyboardButton(text=BTN_SUBSCRIPTION, callback_data="manage_sub"),
        ],
        [
            InlineKeyboardButton(text=BTN_FAQ, callback_data="faq_menu"),
            InlineKeyboardButton(text=BTN_SUPPORT_SHORT, callback_data="support"),
        ],
        [InlineKeyboardButton(text=BTN_POLICY, callback_data="project_policy")],
        [InlineKeyboardButton(text=BTN_REFERRAL, callback_data="referral_program")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_PURCHASE_PROMO, callback_data="purchase_promo")],
        [InlineKeyboardButton(text=BTN_PURCHASE_PLANS, callback_data="purchase_plans")],
        [InlineKeyboardButton(text=BTN_EXIT, callback_data="main_menu")],
    ])


def back_to_purchase_hub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row("tariffs", back_text=BTN_BACK_TARIFFS),
    ])


def project_policy_kb(
    *,
    privacy_url: str,
    terms_url: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_PRIVACY_POLICY, url=privacy_url)],
        [InlineKeyboardButton(text=BTN_TERMS_OF_SERVICE, url=terms_url)],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def _faq_button_title(title: str, *, max_len: int = 42) -> str:
    t = (title or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def faq_list_kb(articles: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=_faq_button_title(a["title"]),
            callback_data=f"faq:article:{a['id']}",
        )]
        for a in articles
    ]
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_article_nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К списку FAQ", callback_data="faq_menu")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def plans_kb(
    plans: list[Plan],
    *,
    extend: bool = False,
    quotes: dict[str, PriceQuote] | None = None,
) -> InlineKeyboardMarkup:
    prefix = "extend_plan" if extend else "select_plan"
    rows = []
    for plan in plans:
        quote = (quotes or {}).get(plan["id"])
        final_price = quote.final_price if quote else None
        rows.append([InlineKeyboardButton(
            text=plan_button_label(plan, final_price=final_price),
            callback_data=f"{prefix}:{plan['id']}",
        )])
    if extend:
        rows.append(nav_row("manage_sub"))
    else:
        rows.append(nav_row("tariffs", back_text=BTN_BACK_TARIFFS))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(
    plan_id: str,
    *,
    methods: list[PaymentMethod],
    extend: bool = False,
    quote: PriceQuote | None = None,
    back_callback: str | None = None,
    extend_sub_id: int | None = None,
) -> InlineKeyboardMarkup:
    rows = []
    for m in methods:
        if extend and extend_sub_id:
            cb_data = f"pay_extend:{plan_id}:{m['key']}:{extend_sub_id}"
        elif extend:
            cb_data = f"pay_extend:{plan_id}:{m['key']}"
        else:
            cb_data = f"pay:{plan_id}:{m['key']}"
        rows.append([InlineKeyboardButton(
            text=f"{m['emoji']} {m['name']}",
            callback_data=cb_data,
        )])
    if back_callback:
        back_data = back_callback
        back_text = BTN_BACK_TARIFFS
    elif extend:
        back_data = "extend_menu"
        back_text = BTN_BACK
    else:
        back_data = "tariffs"
        back_text = BTN_BACK_TARIFFS
    rows.append(nav_row(back_data, back_text=back_text))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_scenario_kb(
    plan_id: str,
    method_key: str,
    *,
    extend: bool = False,
    extend_sub_id: int | None = None,
) -> InlineKeyboardMarkup:
    ext_flag = "1" if extend else "0"
    sub_suffix = f":{extend_sub_id}" if extend and extend_sub_id else ""
    back_prefix = "extend_plan" if extend else "select_plan"
    scenarios = [
        ("✅ Оплачено", "CONFIRMED"),
        ("❌ Отмена", "CANCELED"),
        ("⏳ Ожидание", "PENDING"),
        ("↩️ Возврат", "CHARGEBACKED"),
        ("💥 Ошибка API", "CREATE_ERROR"),
    ]
    rows = [
        [InlineKeyboardButton(
            text=label,
            callback_data=f"test_scenario:{plan_id}:{method_key}:{scenario}:{ext_flag}{sub_suffix}",
        )]
        for label, scenario in scenarios
    ]
    rows.append(nav_row(f"{back_prefix}:{plan_id}"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(
    payment_url: str,
    tx_id: str,
    *,
    test_mode: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if payment_url:
        rows.append([InlineKeyboardButton(text=BTN_PAY, url=payment_url)])
    if test_mode:
        rows += [
            [InlineKeyboardButton(
                text="🔍 Не оплачено",
                callback_data=f"test_check_pay:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="✅ Симуляция оплаты",
                callback_data=f"test_sim_pay:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="📡 Webhook: успех",
                callback_data=f"test_sim_webhook:{tx_id}",
            )],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"test_sim_cancel:{tx_id}",
                ),
                InlineKeyboardButton(
                    text="⏱ Истекло",
                    callback_data=f"test_sim_expired:{tx_id}",
                ),
            ],
            [InlineKeyboardButton(
                text="⚠️ Неверная сумма",
                callback_data=f"test_sim_mismatch:{tx_id}",
            )],
        ]
    else:
        rows.append([InlineKeyboardButton(
            text=BTN_CHECK_PAY,
            callback_data=f"check_pay:{tx_id}",
        )])
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sub_action_label(sub: dict) -> str:
    if is_trial_email(sub.get("client_email")):
        return "🎁 Пробная"
    return subscription_short_label(sub)


def _refund_order_button_label(order: dict) -> str:
    kind = "🔄" if (order.get("order_type") or "new") == "extend" else "📦"
    plan = order.get("plan_name") or "тариф"
    if len(plan) > 12:
        plan = plan[:9] + "..."
    return f"{kind} #{order['id']} · {plan} · {order.get('amount', 0)}₽"


def subscriptions_picker_kb(subs: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=_sub_action_label(sub),
            callback_data=f"manage_sub:{sub['id']}",
        )]
        for sub in subs
    ]
    if len(subs) > 1:
        rows.append([InlineKeyboardButton(
            text="🔍 Поиск по email",
            callback_data="sub_search_email",
        )])
    if any(not is_trial_email(sub.get("client_email")) for sub in subs):
        rows.append([InlineKeyboardButton(
            text="➕ Купить еще одну",
            callback_data="tariffs",
        )])
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_email_search_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row("manage_sub"),
    ])


def subscription_manage_kb(
    sub_id: int,
    *,
    refund_tickets: list[dict] | None = None,
    can_request_refund: bool = True,
    can_extend: bool = True,
    is_trial: bool = False,
    back_callback: str = "main_menu",
) -> InlineKeyboardMarkup:
    refund_tickets = refund_tickets or []
    rows = [
        [InlineKeyboardButton(text="🔗 Ссылка и QR", callback_data=f"sub_link:{sub_id}")],
    ]
    purchase_extend_row: list[InlineKeyboardButton] = []
    if not is_trial and can_extend:
        purchase_extend_row.append(InlineKeyboardButton(
            text="🔄 Продлить подписку",
            callback_data=f"extend_sub:{sub_id}",
        ))
    if not is_trial:
        purchase_extend_row.append(InlineKeyboardButton(
            text="➕ Купить еще одну",
            callback_data="tariffs",
        ))
    if purchase_extend_row:
        rows.append(purchase_extend_row)
    if not is_trial:
        rows.append([InlineKeyboardButton(
            text="✏️ Переименовать",
            callback_data=f"sub_rename:{sub_id}",
        )])
    for ticket in refund_tickets:
        order_id = ticket.get("order_id")
        label = f"💬 Возврат заказа #{order_id}" if order_id else f"💬 Возврат #{ticket['id']}"
        rows.append([InlineKeyboardButton(
            text=label,
            callback_data=f"ticket_view:{ticket['id']}",
        )])
    if can_request_refund and not is_trial:
        rows.append([InlineKeyboardButton(
            text="💸 Запросить возврат",
            callback_data=f"refund:{sub_id}",
        )])
    if not is_trial:
        rows.append([InlineKeyboardButton(
            text=BTN_SERVER_STATUS,
            callback_data=f"server_status:{sub_id}",
        )])
    rows.append(nav_row(back_callback))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_menu_kb(tickets: list) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in tickets:
        if t.get("category") == "refund":
            continue
        cat = "🛠" if t["category"] == "support" else "📁"
        rows.append([InlineKeyboardButton(
            text=f"{cat} Тикет #{t['id']}",
            callback_data=f"ticket_view:{t['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Создать обращение",
        callback_data="ticket_create",
    )])
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_category_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Техподдержка", callback_data="ticket_new:support")],
        [InlineKeyboardButton(text="📁 Другое", callback_data="ticket_new:other")],
        nav_row("support"),
    ])


def ticket_view_kb(
    ticket_id: int,
    *,
    is_open: bool = True,
    is_refund: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_open:
        rows.append([InlineKeyboardButton(
            text="💬 Начать переписку",
            callback_data=f"ticket_session:{ticket_id}",
        )])
    back_data = "manage_sub" if is_refund else "support"
    back_text = BTN_SUBSCRIPTION if is_refund else BTN_BACK
    rows.append(nav_row(back_data, back_text=back_text))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def ticket_session_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⏹ Завершить переписку",
            callback_data=f"ticket_session_end:{ticket_id}",
        )],
        nav_row(f"ticket_view:{ticket_id}", back_text="◀️ К тикету"),
    ])


def payment_failed_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💬 Обратиться в поддержку",
            callback_data=f"support_from_order:{order_id}",
        )],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def refund_pick_kb(sub_id: int, orders: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=_refund_order_button_label(order),
            callback_data=f"refund_pick:{sub_id}:{order['id']}",
        )]
        for order in orders
    ]
    rows.append(nav_row("manage_sub"))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def refund_confirm_kb(sub_id: int, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Да, запросить возврат",
            callback_data=f"refund_confirm:{sub_id}:{order_id}",
        )],
        nav_row(f"refund:{sub_id}"),
        [InlineKeyboardButton(text="❌ Отмена", callback_data="manage_sub")],
    ])


def grant_promo_choice_kb(promo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔄 Продлить текущую подписку",
            callback_data=f"grant_promo:extend:{promo_id}",
        )],
        [InlineKeyboardButton(
            text="➕ Новая подписка бесплатно",
            callback_data=f"grant_promo:new:{promo_id}",
        )],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def grant_promo_extend_picker_kb(promo_id: int, subs: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=subscription_short_label(sub),
            callback_data=f"grant_promo:extend_sub:{promo_id}:{sub['id']}",
        )]
        for sub in subs
    ]
    rows.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data=f"grant_promo:back:{promo_id}",
    )])
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def extend_sub_picker_kb(
    subs: list[dict],
    *,
    plan_id: str | None = None,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=subscription_short_label(sub),
            callback_data=(
                f"purchase_extend_sub:{plan_id}:{sub['id']}"
                if plan_id
                else f"extend_sub:{sub['id']}"
            ),
        )]
        for sub in subs
    ]
    back = f"select_plan:{plan_id}" if plan_id else "manage_sub"
    rows.append(nav_row(back, back_text=BTN_BACK_TARIFFS if plan_id else BTN_BACK))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def purchase_action_kb(plan_id: str, *, can_extend: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_extend:
        rows.append([InlineKeyboardButton(
            text="🔄 Продлить подписку",
            callback_data=f"purchase_extend:{plan_id}",
        )])
    rows.append([InlineKeyboardButton(
        text="➕ Купить новую",
        callback_data=f"purchase_new:{plan_id}",
    )])
    rows.append(nav_row("tariffs", back_text=BTN_BACK_TARIFFS))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def sub_name_prompt_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", callback_data="sub_name_confirm")],
        nav_row("tariffs", back_text=BTN_BACK_TARIFFS),
    ])


def no_subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TARIFFS, callback_data="tariffs")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def expiry_reminder_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TARIFFS, callback_data="tariffs")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def trial_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Активировать", callback_data="trial_confirm")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def server_status_kb(*, back_callback: str = "main_menu") -> InlineKeyboardMarkup:
    if back_callback == "main_menu":
        rows = [[InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")]]
    else:
        rows = [nav_row(back_callback)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_program_kb(share_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", url=share_url)],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def fulfillment_success_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📲 Как подключить подписку",
            callback_data="faq:builtin:activation",
        )],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])
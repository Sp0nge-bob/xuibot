from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config.payments import PaymentMethod
from config.plans import Plan
from config.trial import is_trial_email
from services.pricing import PriceQuote

from ui.theme import (
    BTN_BACK,
    BTN_BACK_TARIFFS,
    BTN_CHECK_PAY,
    BTN_HOME,
    BTN_PAY,
    BTN_PROMO,
    BTN_SUBSCRIPTION,
    BTN_SUPPORT_SHORT,
    BTN_TARIFFS,
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


def main_menu_kb(*, trial_available: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if trial_available:
        rows.append([InlineKeyboardButton(text=BTN_TRIAL, callback_data="trial_offer")])
    rows += [
        [
            InlineKeyboardButton(text=BTN_TARIFFS, callback_data="tariffs"),
            InlineKeyboardButton(text=BTN_SUBSCRIPTION, callback_data="manage_sub"),
        ],
        [
            InlineKeyboardButton(text=BTN_PROMO, callback_data="promo_enter"),
            InlineKeyboardButton(text=BTN_SUPPORT_SHORT, callback_data="support"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_kb(plans: list[Plan], *, extend: bool = False) -> InlineKeyboardMarkup:
    prefix = "extend_plan" if extend else "select_plan"
    rows = [
        [InlineKeyboardButton(
            text=plan_button_label(plan),
            callback_data=f"{prefix}:{plan['id']}",
        )]
        for plan in plans
    ]
    if extend:
        rows.append(nav_row("manage_sub"))
    else:
        rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(
    plan_id: str,
    *,
    methods: list[PaymentMethod],
    extend: bool = False,
    quote: PriceQuote | None = None,
) -> InlineKeyboardMarkup:
    prefix = "pay_extend" if extend else "pay"
    rows = [
        [InlineKeyboardButton(
            text=f"{m['emoji']} {m['name']}",
            callback_data=f"{prefix}:{plan_id}:{m['key']}",
        )]
        for m in methods
    ]
    back_data = "extend_menu" if extend else "tariffs"
    rows.append(nav_row(back_data, back_text=BTN_BACK_TARIFFS if not extend else BTN_BACK))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_scenario_kb(plan_id: str, method_key: str, *, extend: bool = False) -> InlineKeyboardMarkup:
    ext_flag = "1" if extend else "0"
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
            callback_data=f"test_scenario:{plan_id}:{method_key}:{scenario}:{ext_flag}",
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
    return "🎁 Пробная" if is_trial_email(sub.get("client_email")) else "✅ Платная"


def _refund_order_button_label(order: dict) -> str:
    kind = "🔄" if (order.get("order_type") or "new") == "extend" else "📦"
    plan = order.get("plan_name") or "тариф"
    if len(plan) > 12:
        plan = plan[:9] + "..."
    return f"{kind} #{order['id']} · {plan} · {order.get('amount', 0)}₽"


def subscriptions_manage_kb(
    subs: list[dict],
    *,
    refund_tickets: dict[int, list[dict]] | None = None,
    can_request_refund: dict[int, bool] | None = None,
    can_extend: bool = True,
) -> InlineKeyboardMarkup:
    refund_tickets = refund_tickets or {}
    can_request_refund = can_request_refund or {}
    rows: list[list[InlineKeyboardButton]] = []
    has_paid = False
    for sub in subs:
        label = _sub_action_label(sub)
        rows.append([InlineKeyboardButton(
            text=f"🔗 {label} — ссылка и QR",
            callback_data=f"sub_link:{sub['id']}",
        )])
        if not is_trial_email(sub.get("client_email")):
            has_paid = True
            for ticket in refund_tickets.get(sub["id"], []):
                order_id = ticket.get("order_id")
                btn = f"💬 Возврат заказа #{order_id}" if order_id else f"💬 Возврат #{ticket['id']}"
                rows.append([InlineKeyboardButton(
                    text=f"{label} — {btn}",
                    callback_data=f"ticket_view:{ticket['id']}",
                )])
            if can_request_refund.get(sub["id"], True):
                rows.append([InlineKeyboardButton(
                    text=f"💸 {label} — запросить возврат",
                    callback_data=f"refund:{sub['id']}",
                )])
    if has_paid and can_extend:
        rows.append([InlineKeyboardButton(text="🔄 Продлить платную", callback_data="extend_menu")])
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_manage_kb(
    sub_id: int,
    *,
    refund_tickets: list[dict] | None = None,
    can_request_refund: bool = True,
    can_extend: bool = True,
    is_trial: bool = False,
) -> InlineKeyboardMarkup:
    refund_tickets = refund_tickets or []
    rows = [
        [InlineKeyboardButton(text="🔗 Ссылка и QR", callback_data=f"sub_link:{sub_id}")],
    ]
    if not is_trial and can_extend:
        rows.append([InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="extend_menu")])
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
    rows.append([InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")])
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


def no_subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_TARIFFS, callback_data="tariffs")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def trial_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Активировать", callback_data="trial_confirm")],
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BTN_HOME, callback_data="main_menu")],
    ])
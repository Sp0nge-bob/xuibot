from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config.payments import get_payment_methods
from config.plans import Plan
from config.settings import settings
from services.pricing import PriceQuote


def main_menu_kb(has_subscription: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📦 Тарифы", callback_data="tariffs")],
    ]
    if has_subscription:
        rows.append([
            InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_sub")
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="⚙️ Управление подпиской", callback_data="manage_sub")
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def plans_kb(plans: list[Plan], *, extend: bool = False) -> InlineKeyboardMarkup:
    prefix = "extend_plan" if extend else "select_plan"
    rows = []
    for plan in plans:
        rows.append([
            InlineKeyboardButton(
                text=f"{plan['name']} — {plan['price']} ₽",
                callback_data=f"{prefix}:{plan['id']}",
            )
        ])
    back_data = "manage_sub" if extend else "main_menu"
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data=back_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(
    plan_id: str,
    *,
    extend: bool = False,
    quote: PriceQuote | None = None,
) -> InlineKeyboardMarkup:
    methods = get_payment_methods(settings.PLATEGA_SBP_METHOD, settings.PLATEGA_CRYPTO_METHOD)
    prefix = "pay_extend" if extend else "pay"
    rows = [
        [InlineKeyboardButton(
            text=f"{m['emoji']} {m['name']}",
            callback_data=f"{prefix}:{plan_id}:{m['key']}",
        )]
        for m in methods
    ]
    ext_flag = "1" if extend else "0"
    promo_label = "🎟 Промокод ✓" if quote and quote.has_discount else "🎟 Промокод"
    rows.append([InlineKeyboardButton(
        text=promo_label,
        callback_data=f"promo_enter:{plan_id}:{ext_flag}",
    )])
    if quote and quote.has_discount:
        rows.append([InlineKeyboardButton(
            text="✖ Убрать промокод",
            callback_data=f"promo_clear:{plan_id}:{ext_flag}",
        )])
    back_data = "extend_menu" if extend else "tariffs"
    rows.append([InlineKeyboardButton(text="« Назад", callback_data=back_data)])
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def test_scenario_kb(plan_id: str, method_key: str, *, extend: bool = False) -> InlineKeyboardMarkup:
    ext_flag = "1" if extend else "0"
    back_prefix = "extend_plan" if extend else "select_plan"
    scenarios = [
        ("✅ CONFIRMED", "CONFIRMED"),
        ("❌ CANCELED", "CANCELED"),
        ("⏳ PENDING", "PENDING"),
        ("↩️ CHARGEBACKED", "CHARGEBACKED"),
        ("💥 Ошибка API", "CREATE_ERROR"),
    ]
    rows = [
        [InlineKeyboardButton(
            text=label,
            callback_data=f"test_scenario:{plan_id}:{method_key}:{scenario}:{ext_flag}",
        )]
        for label, scenario in scenarios
    ]
    rows.append([InlineKeyboardButton(
        text="« Назад",
        callback_data=f"{back_prefix}:{plan_id}",
    )])
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_kb(
    payment_url: str,
    tx_id: str,
    *,
    test_mode: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=payment_url)],
    ]
    if test_mode:
        rows += [
            [InlineKeyboardButton(
                text="🔍 Проверить (не оплачено)",
                callback_data=f"test_check_pay:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="✅ Симулировать оплату (check_pay)",
                callback_data=f"test_sim_pay:{tx_id}",
            )],
            [InlineKeyboardButton(
                text="📡 Webhook: оплата прошла",
                callback_data=f"test_sim_webhook:{tx_id}",
            )],
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data=f"test_sim_cancel:{tx_id}",
                ),
                InlineKeyboardButton(
                    text="⏱ Истекло 30м",
                    callback_data=f"test_sim_expired:{tx_id}",
                ),
            ],
            [InlineKeyboardButton(
                text="⚠️ Webhook: неверная сумма",
                callback_data=f"test_sim_mismatch:{tx_id}",
            )],
        ]
    else:
        rows.append([InlineKeyboardButton(
            text="🔄 Проверить оплату",
            callback_data=f"check_pay:{tx_id}",
        )])
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_manage_kb(sub_id: int, *, refund_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔗 Ссылка и QR", callback_data=f"sub_link:{sub_id}")],
        [InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="extend_menu")],
    ]
    if refund_id:
        rows.append([InlineKeyboardButton(
            text="💬 Переписка по возврату",
            callback_data=f"refund_chat:{refund_id}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            text="💸 Запросить возврат",
            callback_data=f"refund:{sub_id}",
        )])
    rows.append([InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def refund_chat_kb(refund_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Написать сообщение",
            callback_data=f"refund_reply:{refund_id}",
        )],
        [InlineKeyboardButton(text="« Управление подпиской", callback_data="manage_sub")],
        [InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")],
    ])


def refund_confirm_kb(sub_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, запросить возврат", callback_data=f"refund_confirm:{sub_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="manage_sub")],
    ])


def no_subscription_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Выбрать тариф", callback_data="tariffs")],
        [InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")],
    ])


def back_to_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Главное меню", callback_data="main_menu")],
    ])
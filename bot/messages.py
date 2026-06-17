"""Тексты интерфейса бота."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.plans import Plan
from config.settings import settings
from config.trial import TRIAL_COOLDOWN_DAYS, TRIAL_DAYS, TRIAL_TRAFFIC_GB, is_trial_email
from services.pricing import PriceQuote


def _user_line(first_name: Optional[str], username: Optional[str]) -> str:
    name = first_name or "Пользователь"
    if username:
        return f"👤 <b>{name}</b> (@{username})"
    return f"👤 <b>{name}</b>"


def _format_date(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", ""))
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date[:10]


def _days_left(iso_date: str) -> int:
    try:
        end = datetime.fromisoformat(iso_date.replace("Z", ""))
        return max(0, (end - datetime.utcnow()).days)
    except ValueError:
        return 0


def _sub_kind_label(sub: Dict[str, Any]) -> str:
    return "🎁 Пробная" if is_trial_email(sub.get("client_email")) else "✅ Платная"


def _sub_menu_line(sub: Dict[str, Any]) -> str:
    end = _format_date(sub["end_date"])
    left = _days_left(sub["end_date"])
    traffic = "безлимит" if sub.get("traffic_limit_gb", 0) == 0 else f"{sub['traffic_limit_gb']} ГБ"
    return f"{_sub_kind_label(sub)} · до <b>{end}</b> · {left} дн. · {traffic}"


def _promo_discount_label(promo: Dict[str, Any]) -> str:
    if promo.get("discount_type") == "percent":
        return f"{promo['discount_value']}%"
    return f"{promo['discount_value']} ₽"


def _pending_discount_menu_lines(promo: Dict[str, Any], expires_at: str) -> List[str]:
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "")).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        expires = expires_at[:16]
    allowed = (promo.get("plan_ids") or "").strip()
    plans_hint = f"<code>{allowed}</code>" if allowed else "любой тариф"
    return [
        "🎟 <b>Активная скидка</b>",
        f"   └ Код: <code>{promo['code']}</code> · <b>−{_promo_discount_label(promo)}</b>",
        f"   └ Тарифы: {plans_hint}",
        f"   └ Действует до: <b>{expires} UTC</b>",
        "   └ Применится при оплате в «Тарифы»",
    ]


def main_menu_text(
    first_name: Optional[str],
    username: Optional[str],
    subscriptions: List[Dict[str, Any]],
    *,
    announcement: Optional[str] = None,
    pending_discount_promo: Optional[Dict[str, Any]] = None,
    pending_discount_expires_at: Optional[str] = None,
) -> str:
    lines = ["🌐 <b>VPN Bot</b>", "━━━━━━━━━━━━━━━━", _user_line(first_name, username), ""]

    if announcement:
        lines.append(announcement)
        lines.append("")

    if not subscriptions:
        lines.append("📊 <b>Подписка:</b> ❌ Нет активной")
    elif len(subscriptions) == 1:
        lines += ["📊 <b>Подписка:</b>", f"   └ {_sub_menu_line(subscriptions[0])}"]
    else:
        lines.append("📊 <b>Подписки:</b>")
        for sub in subscriptions:
            lines.append(f"   └ {_sub_menu_line(sub)}")

    if pending_discount_promo and pending_discount_expires_at:
        lines += ["", *_pending_discount_menu_lines(
            pending_discount_promo, pending_discount_expires_at,
        )]

    if settings.TEST_MODE:
        lines += ["", "⚠️ <i>Тестовый режим включён</i>"]

    lines += ["", "Выберите действие:"]
    return "\n".join(lines)


def _renewal_note(*, extend: bool = False, has_active_sub: bool = False) -> str:
    if extend:
        return "ℹ️ Срок будет <b>добавлен</b> к текущей подписке."
    if has_active_sub:
        return (
            "ℹ️ У вас уже есть активная подписка.\n"
            "Оплата <b>продлит</b> её — новый ключ не создаётся."
        )
    return ""


def plans_menu_text(*, has_active_sub: bool = False) -> str:
    lines = [
        "📦 <b>Тарифы</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Выберите подходящий план.",
        "После выбора тарифа вы сможете выбрать способ оплаты.",
    ]
    note = _renewal_note(has_active_sub=has_active_sub)
    if note:
        lines += ["", note]
    return "\n".join(lines)


def _price_lines(quote: PriceQuote | None, plan: Plan) -> list[str]:
    if quote and quote.has_discount:
        return [
            f"💰 Цена: <s>{quote.base_price} ₽</s> → <b>{quote.final_price} ₽</b>",
            f"🎟 Скидка: <b>−{quote.discount_amount} ₽</b> ({quote.promo_code})",
        ]
    return [f"💰 Стоимость: <b>{plan['price']} ₽</b>"]


def plan_card_text(
    plan: Plan,
    *,
    extend: bool = False,
    has_active_sub: bool = False,
    quote: PriceQuote | None = None,
) -> str:
    traffic = "безлимит" if plan["traffic_gb"] == 0 else f"{plan['traffic_gb']} ГБ"
    is_renewal = extend or has_active_sub
    action = "Продление" if is_renewal else "Тариф"
    lines = [
        f"📦 <b>{action}: {plan['name']}</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"⏱ Срок: <b>{plan['days']} дн.</b>",
        f"📊 Трафик: {traffic}",
        *_price_lines(quote, plan),
    ]
    note = _renewal_note(extend=extend, has_active_sub=has_active_sub)
    if note:
        lines += ["", note]
    lines += ["", "Выберите способ оплаты:"]
    return "\n".join(lines)


def payment_method_text(plan: Plan, method_name: str, method_emoji: str) -> str:
    return (
        f"💳 <b>Оплата</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"📦 Тариф: <b>{plan['name']}</b> — {plan['price']} ₽\n"
        f"💰 Способ: {method_emoji} <b>{method_name}</b>\n\n"
        "Нажмите кнопку ниже для перехода к оплате."
    )


def test_payment_text(
    plan: Plan,
    method_name: str,
    method_emoji: str,
    *,
    extend: bool = False,
    has_active_sub: bool = False,
    quote: PriceQuote | None = None,
    request_preview: str | None = None,
) -> str:
    is_renewal = extend or has_active_sub
    action = "Продление" if is_renewal else "Тариф"
    final_amount = quote.final_price if quote else plan["price"]
    price_line = (
        f"📦 {action}: <b>{plan['name']}</b> — <s>{quote.base_price}</s> <b>{quote.final_price} ₽</b>"
        if quote and quote.has_discount
        else f"📦 {action}: <b>{plan['name']}</b> — <b>{plan['price']} ₽</b>"
    )
    lines = [
        "⚠️ <b>Тестовый режим</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        price_line,
        f"💰 Способ: {method_emoji} <b>{method_name}</b>",
        f"💳 К оплате: <b>{final_amount} ₽</b>",
    ]
    if quote and quote.has_discount:
        lines.append(f"🎟 Промокод: <code>{quote.promo_code}</code> (−{quote.discount_amount} ₽)")
    note = _renewal_note(extend=extend, has_active_sub=has_active_sub)
    if note:
        lines += ["", note]
    if request_preview:
        lines += [
            "",
            "📡 <b>Запрос к Platega (не отправляется):</b>",
            request_preview,
            "",
            "📥 <b>Ожидаемый ответ:</b>",
            "<code>{\"transactionId\": \"...\", \"status\": \"PENDING\", \"redirect\": \"...\"}</code>",
        ]
    lines += [
        "",
        "Реальные деньги не списываются.",
        "Выберите сценарий:",
    ]
    return "\n".join(lines)


def test_scenario_result_text(scenario: str, tx_id: str | None = None) -> str:
    labels = {
        "CONFIRMED": "✅ Оплачено",
        "CANCELED": "❌ Отмена",
        "PENDING": "⏳ Ожидание оплаты",
        "CHARGEBACKED": "↩️ Возврат средств",
        "CREATE_ERROR": "💥 Ошибка API",
    }
    label = labels.get(scenario, scenario)
    lines = [
        "🧪 <b>Симуляция Platega</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Сценарий: {label}",
    ]
    if tx_id:
        lines.append(f"🆔 transactionId: <code>{tx_id}</code>")
    return "\n".join(lines)


def _subscription_detail_block(sub: Dict[str, Any], sub_link: Optional[str]) -> list[str]:
    end = _format_date(sub["end_date"])
    left = _days_left(sub["end_date"])
    traffic = "безлимит" if sub.get("traffic_limit_gb", 0) == 0 else f"{sub['traffic_limit_gb']} ГБ"
    lines = [
        f"<b>{_sub_kind_label(sub)}</b>",
        f"📅 Действует до: <b>{end}</b> ({left} дн.)",
        f"📊 Трафик: {traffic}",
        f"👤 Клиент: <code>{sub['client_email']}</code>",
    ]
    if sub_link:
        lines += [f"🔗 <b>Ссылка:</b>", f"<code>{sub_link}</code>"]
    return lines


def subscription_manage_text(sub: Dict[str, Any], sub_link: Optional[str]) -> str:
    lines = [
        "⚙️ <b>Управление подпиской</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        *_subscription_detail_block(sub, sub_link),
        "",
        "Что хотите сделать?",
    ]
    return "\n".join(lines)


def subscriptions_manage_text(
    subs: List[Dict[str, Any]],
    sub_links: Dict[int, Optional[str]],
) -> str:
    lines = ["⚙️ <b>Управление подписками</b>", "━━━━━━━━━━━━━━━━", ""]
    for i, sub in enumerate(subs):
        if i > 0:
            lines.append("──────────────")
            lines.append("")
        lines.extend(_subscription_detail_block(sub, sub_links.get(sub["id"])))
    lines += ["", "Что хотите сделать?"]
    return "\n".join(lines)


def no_subscription_text() -> str:
    return (
        "⚙️ <b>Управление подпиской</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "У вас пока нет активной подписки.\n"
        "Оформите тариф или возьмите пробный период в главном меню."
    )


def trial_offer_text() -> str:
    return (
        "🎁 <b>Пробный период</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"⏱ Срок: <b>{TRIAL_DAYS} дн.</b>\n"
        f"📊 Трафик: <b>{TRIAL_TRAFFIC_GB} ГБ</b>\n"
        f"👤 Клиент: <code>tgfree…</code>\n\n"
        f"Доступен <b>1 раз в {TRIAL_COOLDOWN_DAYS} дн.</b> на аккаунт Telegram.\n"
        "После окончания можно оформить платный тариф.\n\n"
        "Активировать пробный период?"
    )


def admin_trial_menu_text(grants: list) -> str:
    lines = [
        "🎁 <b>Пробные подписки</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Сброс снимает лимит 90 дней и удаляет активную пробную подписку с панели.",
        "",
    ]
    if not grants:
        lines.append("Выдач пробного периода пока не было.")
    else:
        lines.append("<b>Последние выдачи:</b>")
        for g in grants:
            label = g.get("username") or g.get("first_name") or str(g["tg_id"])
            date = str(g["granted_at"])[:10]
            lines.append(f"• {label} (<code>{g['tg_id']}</code>) — {date}")
    lines += ["", "Введите TG ID для сброса — кнопка ниже."]
    return "\n".join(lines)


def admin_trial_reset_all_confirm_text(*, trial_count: int, grants_count: int) -> str:
    return (
        "🗑 <b>Сброс всех пробных подписок</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Активных пробных подписок: <b>{trial_count}</b>\n"
        f"Записей о выдаче (лимит 90 дн.): <b>{grants_count}</b>\n\n"
        "Будет выполнено:\n"
        "• удаление tgfree* с панели на всех нодах\n"
        "• деактивация пробных подписок в БД\n"
        "• сброс лимита пробного периода для всех\n\n"
        "Продолжить?"
    )


def _truncate_preview(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def admin_start_text_menu_text(announcement: Optional[str]) -> str:
    lines = [
        "📢 <b>Сообщение /start</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Произвольный блок для новостей, скидок и акций.",
        "Показывается в главном меню <b>между приветствием и статусом подписки</b>.",
        "",
        "Системные строки (подписка, промокод, тестовый режим, «Выберите действие») "
        "формируются ботом автоматически и не меняются.",
        "",
        "<b>Сейчас:</b>",
    ]
    if announcement:
        lines.append(_truncate_preview(announcement))
    else:
        lines.append("<i>Не задано — показывается только системное меню.</i>")
    return "\n".join(lines)


def admin_start_text_edit_prompt_text() -> str:
    return (
        "✏️ <b>Новое сообщение /start</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте текст для блока новостей/акций.\n"
        "Поддерживается HTML: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, "
        "<code>&lt;code&gt;</code> и т.д.\n\n"
        "Для отмены: /admin"
    )


def admin_debug_entry_confirm_text() -> str:
    return (
        "🧪 <b>Раздел отладки</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Здесь доступны опасные операции:\n"
        "• массовый сброс пробных подписок\n"
        "• очистка всех применений промокодов\n\n"
        "Используйте только для отладки и тестирования.\n\n"
        "Войти в раздел?"
    )


def admin_debug_menu_text(
    *,
    trial_count: int,
    promo_uses: int,
    promo_pending: int,
) -> str:
    return (
        "🧪 <b>Отладка</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🎁 Активных пробных подписок: <b>{trial_count}</b>\n"
        f"🎟 Применений промокодов (promo_uses): <b>{promo_uses}</b>\n"
        f"⏳ Ожидающих скидок (pending): <b>{promo_pending}</b>\n\n"
        "Выберите действие:"
    )


def admin_debug_promo_reset_confirm_text(*, uses_count: int, pending_count: int) -> str:
    return (
        "🎟 <b>Очистка применений промокодов</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Записей promo_uses: <b>{uses_count}</b>\n"
        f"Ожидающих скидок: <b>{pending_count}</b>\n\n"
        "Будет выполнено:\n"
        "• удаление всех записей <code>promo_uses</code>\n"
        "• удаление всех ожидающих скидок (<code>promo_pending_discounts</code>)\n"
        "• обнуление <code>used_count</code> у всех промокодов\n\n"
        "Сами промокоды останутся без изменений.\n\n"
        "Продолжить?"
    )


def admin_trial_reset_confirm_text(tg_id: int, label: str) -> str:
    return (
        "🔄 <b>Сброс пробного периода</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Пользователь: {label}\n"
        f"TG ID: <code>{tg_id}</code>\n\n"
        "Будет удалена запись о выдаче пробного периода.\n"
        "Активная пробная подписка (tgfree) будет снята с панели.\n\n"
        "Продолжить?"
    )


def _order_payment_lines(order: Dict[str, Any]) -> list[str]:
    order_type = order.get("order_type") or "new"
    action = "Продление" if order_type == "extend" else "Покупка"
    paid = (order.get("paid_at") or order.get("created_at") or "")[:16].replace("T", " ")
    lines = [
        f"📦 {action}: <b>{order.get('plan_name') or '—'}</b>",
        f"💰 Сумма: <b>{order.get('amount') or 0} ₽</b>",
        f"🆔 ID заказа: <code>{order.get('id')}</code>",
        f"🆔 ID транзакции Platega: <code>{order.get('platega_tx_id') or '—'}</code>",
        f"🕐 Оплачен: <b>{paid or '—'}</b>",
    ]
    if order.get("promo_code"):
        lines.append(f"🎟 Промокод: <code>{order['promo_code']}</code>")
    return lines


def refund_pick_text() -> str:
    return (
        "💸 <b>Запрос на возврат</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Выберите оплату, по которой хотите оформить возврат:"
    )


def refund_confirm_text(order: Dict[str, Any]) -> str:
    lines = [
        "💸 <b>Подтверждение возврата</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Возврат по оплате:",
        "",
        *_order_payment_lines(order),
        "",
        "Отправить запрос администратору?",
        "Подписка останется активной до решения.",
    ]
    return "\n".join(lines)


def refund_request_sent_text(ticket_id: int) -> str:
    return (
        "💸 <b>Запрос на возврат отправлен</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Тикет <code>#{ticket_id}</code> создан.\n"
        "Администратор рассмотрит ваш запрос.\n"
        "Переписка — в «Управление подпиской» → <b>Тикет возврата</b>."
    )


def support_menu_text(tickets: list) -> str:
    open_count = len([t for t in tickets if t.get("category") != "refund"])
    lines = [
        "💬 <b>Поддержка</b>",
        "━━━━━━━━━━━━━━━━",
        "",
    ]
    if open_count:
        lines.append(f"Открытых обращений: <b>{open_count}</b>\n")
    else:
        lines.append("Нет открытых обращений.\n")
    lines.append("Создайте новое или выберите тикет из списка.")
    return "\n".join(lines)


def ticket_view_text(ticket: Dict[str, Any]) -> str:
    from db.tickets import category_label, STATUS_OPEN
    cat = category_label(ticket["category"])
    status = "открыт" if ticket.get("status") == STATUS_OPEN else "закрыт"
    lines = [
        f"🎫 <b>Тикет #{ticket['id']}</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"📁 Категория: <b>{cat}</b>",
        f"📌 Статус: <b>{status}</b>",
        f"🕐 Создан: {(ticket.get('created_at') or '')[:16]}",
    ]
    if ticket.get("client_email"):
        lines.append(f"👤 Клиент: <code>{ticket['client_email']}</code>")
    if ticket.get("order_id"):
        lines += [
            f"🧾 Заказ: <code>#{ticket['order_id']}</code>",
            f"📦 Тариф: <b>{ticket.get('plan_name') or '—'}</b>",
            f"💰 Сумма: <b>{ticket.get('order_amount') or '—'} ₽</b>",
            f"🆔 TX Platega: <code>{ticket.get('platega_tx_id') or '—'}</code>",
        ]
    if ticket.get("status") == STATUS_OPEN:
        lines += ["", "Нажмите «Начать переписку», чтобы отправить сообщение администратору."]
    return "\n".join(lines)


def ticket_session_banner_text(ticket_id: int, category: str, *, is_new: bool = False) -> str:
    from db.tickets import category_label
    header = "🎫 <b>Новый тикет создан</b>" if is_new else "🔴 <b>Активная переписка</b>"
    return (
        f"{header}\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Тикет <code>#{ticket_id}</code> · {category_label(category)}\n\n"
        "Отправляйте сообщения любого типа — текст, фото, голосовые.\n"
        "Они будут переданы администратору.\n\n"
        "«Завершить переписку» — выйти из режима (тикет останется открытым)."
    )


def ticket_created_text(ticket_id: int) -> str:
    return f"✅ Тикет <code>#{ticket_id}</code> создан."


def refund_ticket_approved_user_text(ticket: Dict[str, Any]) -> str:
    ticket_id = ticket["id"]
    lines = [
        "✅ <b>Запрос на возврат одобрен</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Тикет <code>#{ticket_id}</code> закрыт.",
        "",
        "Возврат средств выполняется вручную через платёжную систему.",
        "Когда возврат будет подтверждён, вы получите отдельное уведомление.",
    ]
    if ticket.get("order_id"):
        lines += [
            "",
            f"🧾 Заказ: <code>#{ticket['order_id']}</code>",
            f"📦 Тариф: <b>{ticket.get('plan_name') or '—'}</b>",
            f"💰 Сумма: <b>{ticket.get('order_amount') or '—'} ₽</b>",
        ]
    return "\n".join(lines)


def refund_ticket_rejected_user_text(ticket: Dict[str, Any]) -> str:
    ticket_id = ticket["id"]
    lines = [
        "❌ <b>Запрос на возврат отклонён</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Тикет <code>#{ticket_id}</code> закрыт.",
        "",
        "Если остались вопросы — напишите в поддержку.",
    ]
    if ticket.get("order_id"):
        lines += [
            "",
            f"🧾 Заказ: <code>#{ticket['order_id']}</code>",
            f"📦 Тариф: <b>{ticket.get('plan_name') or '—'}</b>",
            f"💰 Сумма: <b>{ticket.get('order_amount') or '—'} ₽</b>",
        ]
    return "\n".join(lines)


def refund_admin_text(
    tg_id: int,
    username: Optional[str],
    first_name: Optional[str],
    sub: Dict[str, Any],
    order: Dict[str, Any],
) -> str:
    user = f"@{username}" if username else (first_name or str(tg_id))
    lines = [
        "💸 <b>Запрос на возврат</b>",
        "",
        f"👤 Пользователь: {user} (<code>{tg_id}</code>)",
        f"📅 Подписка до: {_format_date(sub['end_date'])}",
        f"👤 Клиент: <code>{sub['client_email']}</code>",
        f"🆔 Подписка #{sub['id']}",
        "",
        "💳 <b>Оплата для возврата:</b>",
        *_order_payment_lines(order),
    ]
    return "\n".join(lines)


def pending_payment_text(
    plan: Plan,
    method_name: str,
    *,
    extend: bool = False,
    has_active_sub: bool = False,
    quote: PriceQuote | None = None,
    expires_in: str | None = None,
    test_mode: bool = False,
    status_note: str | None = None,
) -> str:
    is_renewal = extend or has_active_sub
    action = "Продление" if is_renewal else "Тариф"
    if quote and quote.has_discount:
        price_part = f"<s>{quote.base_price}</s> <b>{quote.final_price} ₽</b>"
    elif quote:
        price_part = f"<b>{quote.final_price} ₽</b>"
    else:
        price_part = f"<b>{plan['price']} ₽</b>"
    title = "⏳ <b>Ожидаем оплату</b> (тест)" if test_mode else "⏳ <b>Ожидаем оплату</b>"
    lines = [title, "━━━━━━━━━━━━━━━━"]
    if status_note:
        lines += ["", f"⚠️ {status_note}"]
    lines += [
        "",
        f"📦 {action}: <b>{plan['name']}</b> — {price_part}",
        f"💳 Способ: <b>{method_name}</b>",
    ]
    if expires_in:
        if expires_in == "00:00:00":
            lines.append("⏱ <b>Время оплаты истекло</b> — создайте новый заказ")
        else:
            lines.append(f"⏱ Истекает через: <b>{expires_in}</b>")
    else:
        lines.append("⏱ Окно оплаты: <b>30 минут</b> с момента создания счёта")
    if quote and quote.has_discount:
        lines.append(f"🎟 Промокод: <code>{quote.promo_code}</code>")
    note = _renewal_note(extend=extend, has_active_sub=has_active_sub)
    if note:
        lines += ["", note]
    lines += [""]
    if test_mode:
        lines += [
            "<i>Тест: таймер ~30 мин, как у Platega.</i>",
            "Кнопки ниже симулируют проверку, оплату, webhook и отмену.",
        ]
    else:
        lines += [
            "После оплаты ключ выдаётся автоматически.",
            "Можно нажать «Проверить оплату», если уже оплатили.",
        ]
    return "\n".join(lines)


def promo_enter_text() -> str:
    return (
        "🎟 <b>Промокоды</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте код в следующем сообщении.\n\n"
        "• <b>Бесплатный тариф</b> — активируется сразу\n"
        "• <b>Скидка</b> — применится к ближайшей оплате в течение 7 дней\n\n"
        "Для отмены: /start или «Главное меню»."
    )


def promo_applied_text(code: str, discount: int, final_price: int) -> str:
    return (
        f"✅ Промокод <code>{code}</code> применён!\n"
        f"Скидка: <b>−{discount} ₽</b>, к оплате: <b>{final_price} ₽</b>"
    )


def admin_plans_text(plans: list) -> str:
    lines = [
        "💰 <b>Цены тарифов</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Нажмите тариф, чтобы изменить цену.",
        "✏️ — цена отличается от дефолта в config/plans.py",
        "",
    ]
    for p in plans:
        default = p.get("default_price", p["price"])
        mark = " ✏️" if p["price"] != default else ""
        lines.append(f"• <b>{p['name']}</b>: {p['price']} ₽{mark}")
    return "\n".join(lines)


def _promo_admin_summary(p: dict) -> str:
    from db.promo_codes import grant_plan_id, is_grant_promo

    if is_grant_promo(p):
        plan_id = grant_plan_id(p) or "?"
        return f"🎁 тариф <code>{plan_id}</code>"
    if p["discount_type"] == "percent":
        return f"{p['discount_value']}%"
    return f"{p['discount_value']} ₽"


def admin_promos_text(promos: list) -> str:
    if not promos:
        return (
            "🎟 <b>Промокоды</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Промокодов пока нет.\n"
            "Создайте первый — кнопка ниже."
        )
    lines = [
        "🎟 <b>Промокоды</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Всего: <b>{len(promos)}</b>",
        "",
    ]
    for p in promos:
        status = "✅" if p.get("is_active") else "⏸"
        disc = _promo_admin_summary(p)
        uses = p.get("used_count") or 0
        max_u = p.get("max_uses")
        uses_str = f"{uses}/{max_u}" if max_u else f"{uses}/∞"
        per_user = p.get("per_user_limit")
        user_lim = "∞" if not per_user else str(per_user)
        lines.append(
            f"{status} <code>{p['code']}</code> — {disc}, "
            f"всего: {uses_str}, на юзера: {user_lim}"
        )
    return "\n".join(lines)


def admin_promo_detail_text(p: dict) -> str:
    from config.plans import get_plan
    from db.promo_codes import grant_plan_id, is_grant_promo

    uses = p.get("used_count") or 0
    max_u = p.get("max_uses")
    uses_str = f"{uses} / {max_u}" if max_u else f"{uses} / ∞ всего"
    per_user = p.get("per_user_limit")
    per_user_str = "∞" if not per_user else str(per_user)
    valid = p.get("valid_until")
    valid_str = valid[:10] if valid else "без срока"
    status = "активен" if p.get("is_active") else "отключён"

    if is_grant_promo(p):
        plan_id = grant_plan_id(p) or "—"
        plan = get_plan(plan_id)
        plan_line = f"<b>{plan['name']}</b> (<code>{plan_id}</code>)" if plan else f"<code>{plan_id}</code>"
        kind_line = f"Тип: <b>бесплатный тариф</b>\nТариф: {plan_line}"
    else:
        disc = _promo_admin_summary(p)
        plans = (p.get("plan_ids") or "").strip() or "все тарифы"
        kind_line = f"Тип: <b>скидка при оплате</b>\nСкидка: <b>{disc}</b>\nТарифы: <code>{plans}</code>"

    return (
        f"🎟 <b>Промокод {p['code']}</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{kind_line}\n"
        f"Статус: {status}\n"
        f"Использований: {uses_str}\n"
        f"На пользователя: <b>{per_user_str}</b> раз\n"
        f"Действует до: {valid_str}"
    )
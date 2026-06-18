"""Тексты интерфейса бота."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from ui.theme import (
    BRAND,
    days_left,
    format_date,
    money,
    price_per_month,
    renewal_hint,
    screen,
    traffic_label,
    user_chip,
)
from config.plans import Plan
from config.settings import settings
from config.trial import TRIAL_COOLDOWN_DAYS, TRIAL_DAYS, TRIAL_TRAFFIC_GB, is_trial_email
from services.pricing import PriceQuote


def _sub_kind_label(sub: Dict[str, Any]) -> str:
    return "🎁 Пробная" if is_trial_email(sub.get("client_email")) else "✅ Платная"


def _sub_menu_line(sub: Dict[str, Any]) -> str:
    end = format_date(sub["end_date"])
    left = days_left(sub["end_date"])
    traffic = traffic_label(sub.get("traffic_limit_gb", 0))
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


def refund_pending_chargeback_notice() -> str:
    return (
        "💸 <b>Возврат средств в обработке</b>\n"
        "Ваша подписка находится в состоянии возврата средств. "
        "Она будет деактивирована, когда возврат подтвердится."
    )


EXTEND_BLOCKED_REFUND_PENDING_MSG = (
    "Продление недоступно: ожидается подтверждение возврата средств от платёжной системы."
)


def main_menu_text(
    first_name: Optional[str],
    username: Optional[str],
    subscriptions: List[Dict[str, Any]],
    *,
    greeting_template: Optional[str] = None,
    announcement: Optional[str] = None,
    refund_pending_chargeback: bool = False,
    pending_discount_promo: Optional[Dict[str, Any]] = None,
    pending_discount_expires_at: Optional[str] = None,
    pending_payment_plan_name: Optional[str] = None,
) -> str:
    blocks: list[str] = [user_chip(first_name, username, template=greeting_template)]

    if announcement:
        blocks.append(announcement)

    if refund_pending_chargeback:
        blocks.append(refund_pending_chargeback_notice())

    if not subscriptions:
        blocks.append(
            "📊 Подписка: пока нет активной.\n"
            "Можно начать с пробного периода или выбрать тариф."
        )
    elif len(subscriptions) == 1:
        blocks.append(f"📊 Ваша подписка:\n{_sub_menu_line(subscriptions[0])}")
    else:
        lines = [f"   └ {_sub_menu_line(sub)}" for sub in subscriptions]
        blocks.append("📊 Ваши подписки:\n" + "\n".join(lines))

    if pending_discount_promo and pending_discount_expires_at:
        blocks.append("\n".join(_pending_discount_menu_lines(
            pending_discount_promo, pending_discount_expires_at,
        )))

    if pending_payment_plan_name:
        blocks.append(
            f"⏳ <b>Незавершённая оплата</b>\n"
            f"   └ Тариф: <b>{pending_payment_plan_name}</b> — нажмите «Вернуться к оплате»"
        )

    footer = "⚠️ <i>Тестовый режим включён</i>" if settings.TEST_MODE else None
    return screen(
        f"🌐 <b>{BRAND}</b>",
        *blocks,
        hint="Выберите действие ниже 👇",
        footer=footer,
    )


def faq_menu_text(count: int) -> str:
    return screen(
        "❓ <b>FAQ</b>",
        f"Ответы на частые вопросы — <b>{count}</b> "
        f"{_ru_articles_word(count)}.",
        hint="Выберите тему ниже 👇",
    )


def faq_empty_text() -> str:
    return screen(
        "❓ <b>FAQ</b>",
        "Пока нет опубликованных статей.",
        hint="Загляните позже или напишите в поддержку.",
    )


def _ru_articles_word(n: int) -> str:
    n = abs(int(n)) % 100
    if 11 <= n <= 14:
        return "статей"
    last = n % 10
    if last == 1:
        return "статья"
    if 2 <= last <= 4:
        return "статьи"
    return "статей"


def plans_menu_text(*, has_active_sub: bool = False) -> str:
    hint = renewal_hint(has_active_sub=has_active_sub) or None
    return screen(
        "📦 <b>Тарифы</b>",
        "Выберите подходящий план — после этого откроется выбор способа оплаты.",
        hint=hint,
    )


def _price_block(quote: PriceQuote | None, plan: Plan) -> str:
    traffic = traffic_label(plan.get("traffic_gb", 0))
    ppm = price_per_month(plan)
    lines = [
        f"⏱ Срок: <b>{plan['days']} дн.</b>",
        f"📊 Трафик: {traffic}",
    ]
    if quote and quote.has_discount:
        lines += [
            f"💰 Цена: <s>{quote.base_price} ₽</s> → {money(quote.final_price)} · ~{ppm} ₽/мес",
            f"🎟 Скидка: <b>−{quote.discount_amount} ₽</b> ({quote.promo_code})",
        ]
    else:
        lines.append(f"💰 Цена: {money(plan['price'])} · ~{ppm} ₽/мес")
    return "\n".join(lines)


def plan_card_text(
    plan: Plan,
    *,
    extend: bool = False,
    has_active_sub: bool = False,
    quote: PriceQuote | None = None,
) -> str:
    is_renewal = extend or has_active_sub
    action = "Продление" if is_renewal else "Тариф"
    hint_parts = [renewal_hint(extend=extend, has_active_sub=has_active_sub), "Выберите способ оплаты:"]
    hint = "\n".join(p for p in hint_parts if p) or None
    return screen(
        f"📦 <b>{action}: {plan['name']}</b>",
        _price_block(quote, plan),
        hint=hint,
    )


def payment_method_text(plan: Plan, method_name: str, method_emoji: str) -> str:
    return screen(
        "💳 <b>Оплата</b>",
        f"📦 Тариф: <b>{plan['name']}</b> — {money(plan['price'])}",
        f"💰 Способ: {method_emoji} <b>{method_name}</b>",
        hint="Нажмите кнопку ниже — откроется страница оплаты.",
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
    if quote and quote.has_discount:
        summary = (
            f"📦 {action}: <b>{plan['name']}</b> — "
            f"<s>{quote.base_price}</s> {money(quote.final_price)}"
        )
    else:
        summary = f"📦 {action}: <b>{plan['name']}</b> — {money(plan['price'])}"
    blocks = [
        summary,
        f"💰 Способ: {method_emoji} <b>{method_name}</b>",
        f"💳 К оплате: {money(final_amount)}",
    ]
    if quote and quote.has_discount:
        blocks.append(f"🎟 Промокод: <code>{quote.promo_code}</code> (−{quote.discount_amount} ₽)")
    renewal = renewal_hint(extend=extend, has_active_sub=has_active_sub)
    if renewal:
        blocks.append(renewal)
    if request_preview:
        blocks.append(
            "📡 <b>Запрос к Platega (не отправляется):</b>\n"
            f"{request_preview}\n\n"
            "📥 <b>Ожидаемый ответ:</b>\n"
            "<code>{\"transactionId\": \"...\", \"status\": \"PENDING\", \"redirect\": \"...\"}</code>"
        )
    return screen(
        "⚠️ <b>Тестовый режим</b>",
        *blocks,
        hint="Реальные деньги не списываются. Выберите сценарий:",
    )


def test_scenario_result_text(scenario: str, tx_id: str | None = None) -> str:
    labels = {
        "CONFIRMED": "✅ Оплачено",
        "CANCELED": "❌ Отмена",
        "PENDING": "⏳ Ожидание оплаты",
        "CHARGEBACKED": "↩️ Возврат средств",
        "CREATE_ERROR": "💥 Ошибка API",
    }
    label = labels.get(scenario, scenario)
    block = f"Сценарий: {label}"
    if tx_id:
        block += f"\n🆔 transactionId: <code>{tx_id}</code>"
    return screen("🧪 <b>Симуляция Platega</b>", block)


def _subscription_detail_block(sub: Dict[str, Any], sub_link: Optional[str]) -> str:
    end = format_date(sub["end_date"])
    left = days_left(sub["end_date"])
    traffic = traffic_label(sub.get("traffic_limit_gb", 0))
    lines = [
        f"<b>{_sub_kind_label(sub)}</b>",
        f"📅 Действует до: <b>{end}</b> ({left} дн.)",
        f"📊 Трафик: {traffic}",
        f"👤 Клиент: <code>{sub['client_email']}</code>",
    ]
    if sub_link:
        lines += [f"🔗 <b>Ссылка:</b>", f"<code>{sub_link}</code>"]
    return "\n".join(lines)


def subscription_manage_text(sub: Dict[str, Any], sub_link: Optional[str]) -> str:
    return screen(
        "⚙️ <b>Подписка</b>",
        _subscription_detail_block(sub, sub_link),
        hint="Что хотите сделать?",
    )


def subscriptions_manage_text(
    subs: List[Dict[str, Any]],
    sub_links: Dict[int, Optional[str]],
) -> str:
    blocks: list[str] = []
    for i, sub in enumerate(subs):
        if i > 0:
            blocks.append("──────────────")
        blocks.append(_subscription_detail_block(sub, sub_links.get(sub["id"])))
    return screen("⚙️ <b>Подписки</b>", *blocks, hint="Что хотите сделать?")


def no_subscription_text() -> str:
    return screen(
        "⚙️ <b>Подписка</b>",
        "У вас пока нет активной подписки.",
        hint="Оформите тариф или возьмите пробный период в главном меню.",
    )


def trial_offer_text() -> str:
    return screen(
        "🎁 <b>Пробный период</b>",
        "\n".join([
            f"⏱ Срок: <b>{TRIAL_DAYS} дн.</b>",
            f"📊 Трафик: <b>{TRIAL_TRAFFIC_GB} ГБ</b>",
            f"👤 Клиент: <code>tgfree…</code>",
        ]),
        f"Доступен <b>1 раз в {TRIAL_COOLDOWN_DAYS} дн.</b> на аккаунт Telegram.\n"
        "После окончания можно оформить платный тариф.",
        hint="Активировать пробный период?",
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


def admin_start_text_menu_text(
    greeting_preview: str,
    announcement: Optional[str],
    *,
    greeting_html_invalid: bool = False,
    announcement_html_invalid: bool = False,
    greeting_is_custom: bool = False,
) -> str:
    from ui.theme import DEFAULT_GREETING_TEMPLATE

    lines = [
        "📢 <b>Экран /start</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "<b>👋 Приветствие</b>",
        "Шаблон с подстановкой имени пользователя.",
        "Плейсхолдеры: <code>{name}</code>, <code>{username}</code>, "
        "<code>{username_line}</code> (пробел + @ник, если есть).",
        "",
        "<b>Сейчас:</b>",
    ]
    if greeting_is_custom and greeting_html_invalid:
        lines.append(
            "⚠️ <i>Шаблон с ошибкой HTML — в меню показывается как обычный текст.</i>"
        )
    lines.append(_truncate_preview(greeting_preview, limit=400))
    if not greeting_is_custom:
        lines.append(
            f"<i>По умолчанию: <code>{DEFAULT_GREETING_TEMPLATE}</code></i>"
        )
    lines += [
        "",
        "<b>📰 Блок новостей</b>",
        "Произвольный текст между приветствием и статусом подписки.",
        "",
        "<b>Сейчас:</b>",
    ]
    if announcement:
        if announcement_html_invalid:
            lines.append(
                "⚠️ <i>Сохранённый текст с ошибкой HTML — в меню показывается как обычный текст.</i>"
            )
        lines.append(_truncate_preview(announcement))
    else:
        lines.append("<i>Не задано.</i>")
    lines += [
        "",
        "Статус подписки, промокод, тестовый режим и кнопки меню "
        "формируются ботом автоматически.",
    ]
    return "\n".join(lines)


def admin_start_greeting_edit_prompt_text() -> str:
    from ui.theme import DEFAULT_GREETING_TEMPLATE

    return (
        "✏️ <b>Шаблон приветствия</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте текст приветствия для главного меню.\n\n"
        "Подстановки:\n"
        "• <code>{name}</code> — имя из Telegram (или «друг»)\n"
        "• <code>{username}</code> — @ник без скобок\n"
        "• <code>{username_line}</code> — « (@ник)», если ник есть\n\n"
        f"Пример: <code>{DEFAULT_GREETING_TEMPLATE}</code>\n\n"
        "Поддерживается HTML. Для отмены: /admin"
    )


def admin_start_text_edit_prompt_text() -> str:
    return (
        "✏️ <b>Блок новостей /start</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Отправьте текст для блока новостей/акций.\n"
        "Поддерживается HTML: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, "
        "<code>&lt;code&gt;</code> и т.д.\n"
        "Каждый открытый тег нужно закрывать: <code>&lt;b&gt;текст&lt;/b&gt;</code>.\n\n"
        "Для отмены: /admin"
    )


def admin_faq_menu_text(articles: list[dict]) -> str:
    published = sum(1 for a in articles if a.get("is_published"))
    lines = [
        "❓ <b>FAQ</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Всего статей: <b>{len(articles)}</b> · опубликовано: <b>{published}</b>",
        "",
        "Создавайте короткие статьи с заголовком, текстом и фото.",
        "Клиенты увидят их в разделе «FAQ» в главном меню.",
    ]
    if articles:
        lines.append("")
        lines.append("<b>Статьи:</b>")
        for a in articles[:12]:
            status = "✅" if a.get("is_published") else "⏸"
            title = (a.get("title") or "")[:48]
            lines.append(f"  {status} <code>#{a['id']}</code> {title}")
        if len(articles) > 12:
            lines.append(f"  … и ещё {len(articles) - 12}")
    return "\n".join(lines)


def admin_faq_detail_text(article: dict, *, photo_count: int) -> str:
    status = "✅ Опубликована" if article.get("is_published") else "⏸ Скрыта"
    body = (article.get("body") or "").strip()
    preview = body[:400] + ("…" if len(body) > 400 else "") if body else "<i>Текст не задан</i>"
    return (
        f"❓ <b>FAQ #{article['id']}</b>\n"
        f"━━━━━━━━━━━━━━━━\n\n"
        f"<b>{article.get('title') or '—'}</b>\n"
        f"{status} · фото: <b>{photo_count}</b>\n\n"
        f"{preview}"
    )


def admin_faq_title_prompt_text() -> str:
    return (
        "✏️ <b>Заголовок FAQ</b>\n\n"
        "Короткое название для кнопки в списке (до 80 символов).\n\n"
        "Отмена: /admin"
    )


def admin_faq_body_prompt_text(*, title: str) -> str:
    return (
        f"📝 <b>Текст статьи</b>\n"
        f"Заголовок: <b>{title}</b>\n\n"
        "Поддерживается HTML: <code>&lt;b&gt;</code>, <code>&lt;i&gt;</code>, "
        "<code>&lt;code&gt;</code> и т.д.\n\n"
        "Отмена: /admin"
    )


def admin_faq_photos_prompt_text(*, count: int) -> str:
    return (
        "🖼 <b>Фото к статье</b>\n\n"
        f"Добавлено фото: <b>{count}</b> (макс. 10).\n"
        "Отправьте изображения сообщениями в чат.\n\n"
        "Когда закончите — нажмите «Готово» или «Пропустить»."
    )


def admin_faq_edit_title_prompt_text() -> str:
    return "✏️ <b>Новый заголовок</b>\n\nОтмена: /admin"


def admin_faq_edit_body_prompt_text() -> str:
    return (
        "📝 <b>Новый текст статьи</b>\n\n"
        "HTML как в Telegram. Отмена: /admin"
    )


def admin_debug_entry_confirm_text() -> str:
    return (
        "🧪 <b>Раздел отладки</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "⚠️ Здесь доступны опасные операции:\n"
        "• массовый сброс пробных подписок\n"
        "• очистка всех применений промокодов\n"
        "• сброс истории всех заказов\n"
        "• сброс учёта всех тикетов\n"
        "• сброс учёта пользователей\n\n"
        "Используйте только для отладки и тестирования.\n\n"
        "Войти в раздел?"
    )


def admin_happ_crypto_text(mode: str) -> str:
    from config.happ_crypto import HAPP_CRYPTO_MODE_LABELS, HAPP_CRYPTO_NONE

    label = HAPP_CRYPTO_MODE_LABELS.get(mode, mode)
    lines = [
        "🔐 <b>Шифрование ссылок Happ</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Текущий режим: <b>{label}</b>",
        "",
        "🔓 <b>Без шифрования</b> — обычная HTTPS-ссылка подписки.",
        "🔐 <b>Crypt4 (локально)</b> — RSA на VPS, <code>happ://crypt4/…</code>, без сети.",
        "🌐 <b>Crypt5 (API)</b> — запрос на crypto.happ.su, <code>happ://crypt5/…</code>.",
        "",
        "<i>Crypt4 и Crypt5 одинаково скрывают ссылку в Happ (не от дешифраторов).</i>",
        "<i>Для шифрования лучше Crypt4 локально — тот же смысл, без запросов к Happ.</i>",
        "<i>Ссылки кэшируются в памяти процесса бота.</i>",
    ]
    if mode != HAPP_CRYPTO_NONE:
        lines += [
            "",
            "Клиент не видит и не может переслать URL подписки.",
        ]
    return "\n".join(lines)


def admin_payment_methods_text(enabled: dict[str, bool]) -> str:
    from config.payments import all_payment_method_definitions

    lines = [
        "💳 <b>Способы оплаты</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Нажмите на способ, чтобы включить или отключить.",
        "Пользователи видят только <b>включённые</b> методы.",
        "",
    ]
    on_count = sum(1 for v in enabled.values() if v)
    for m in all_payment_method_definitions():
        flag = "✅" if enabled.get(m["key"]) else "❌"
        lines.append(
            f"{flag} {m['emoji']} <b>{m['name']}</b> "
            f"(Platega ID <code>{m['platega_id']}</code>)"
        )
    lines += [
        "",
        f"Включено: <b>{on_count}</b> из <b>{len(all_payment_method_definitions())}</b>",
        "",
        "<i>ID методов можно переопределить в .env (PLATEGA_*_METHOD).</i>",
        "<i>Доступность на стороне Platega уточняйте у менеджера.</i>",
    ]
    return "\n".join(lines)


def admin_backup_menu_text(
    *,
    backup_enabled: bool,
    hour_utc: int,
    local_retain: int,
    env_disabled: bool = False,
    admin_disabled: bool = False,
) -> str:
    if env_disabled:
        status = "⛔ <b>Отключён в .env</b> (<code>BACKUP_ENABLED=false</code>)"
    elif admin_disabled:
        status = "⏸ <b>Ежедневный бэкап выключен</b> (вручную в админке)"
    elif backup_enabled:
        status = f"✅ <b>Ежедневный бэкап включён</b> — {hour_utc:02d}:00 UTC"
    else:
        status = "⏸ <b>Ежедневный бэкап выключен</b>"

    return (
        "💾 <b>Бэкап</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"{status}\n\n"
        "Архив содержит:\n"
        "• <code>bot.db</code> — снимок SQLite\n"
        "• <code>manifest.json</code> — статистика\n"
        "• <code>restore.txt</code> — как восстановить\n"
        "• последние логи (если есть)\n\n"
        f"Локальные копии: <code>data/backups/</code> (хранится <b>{local_retain}</b>)\n"
        "Получатели: все ID из <code>BOT_ADMINS</code>.\n\n"
        "Выберите действие:"
    )


def admin_debug_menu_text(
    *,
    trial_count: int,
    promo_uses: int,
    promo_pending: int,
    orders_count: int = 0,
    tickets_count: int = 0,
    ticket_messages_count: int = 0,
    users_count: int = 0,
) -> str:
    return (
        "🧪 <b>Отладка</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🎁 Активных пробных подписок: <b>{trial_count}</b>\n"
        f"🎟 Применений промокодов (promo_uses): <b>{promo_uses}</b>\n"
        f"⏳ Ожидающих скидок (pending): <b>{promo_pending}</b>\n"
        f"🧾 Заказов в истории: <b>{orders_count}</b>\n"
        f"🎫 Тикетов: <b>{tickets_count}</b> · сообщений: <b>{ticket_messages_count}</b>\n"
        f"👥 Пользователей в БД: <b>{users_count}</b>\n\n"
        "Выберите действие:"
    )


def admin_debug_users_reset_confirm_text(*, users_count: int) -> str:
    return (
        "👥 <b>Сброс учёта пользователей</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Записей в <code>users</code>: <b>{users_count}</b>\n\n"
        "Будет выполнено:\n"
        "• удаление всех записей из таблицы <code>users</code>\n\n"
        "Подписки, заказы, тикеты и клиенты на панели останутся.\n"
        "При следующем /start пользователи будут зарегистрированы заново.\n\n"
        "Продолжить?"
    )


def admin_debug_tickets_reset_confirm_text(
    *,
    tickets_count: int,
    messages_count: int,
) -> str:
    return (
        "🎫 <b>Сброс учёта тикетов</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Тикетов в БД: <b>{tickets_count}</b>\n"
        f"Сообщений в переписках: <b>{messages_count}</b>\n\n"
        "Будет выполнено:\n"
        "• удаление всех записей из <code>ticket_messages</code>\n"
        "• удаление всех записей из <code>tickets</code>\n\n"
        "Открытые и закрытые тикеты (возвраты, поддержка) будут удалены.\n"
        "Пользователи и подписки останутся.\n\n"
        "Продолжить?"
    )


def admin_debug_orders_reset_confirm_text(*, orders_count: int) -> str:
    return (
        "🧾 <b>Сброс истории заказов</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Заказов в БД: <b>{orders_count}</b>\n\n"
        "Будет выполнено:\n"
        "• удаление всех записей из <code>orders</code>\n"
        "• отвязка <code>order_id</code> у подписок и тикетов\n"
        "• очистка привязок промокодов к заказам\n\n"
        "Подписки и пользователи останутся.\n\n"
        "Продолжить?"
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
    return screen(
        "💸 <b>Запрос на возврат</b>",
        hint="Выберите оплату, по которой хотите оформить возврат:",
    )


def refund_confirm_text(order: Dict[str, Any]) -> str:
    return screen(
        "💸 <b>Подтверждение возврата</b>",
        "Возврат по оплате:\n\n" + "\n".join(_order_payment_lines(order)),
        hint="Отправить запрос администратору? Подписка останется активной до решения.",
    )


def refund_request_sent_text(ticket_id: int) -> str:
    return screen(
        "💸 <b>Запрос отправлен</b>",
        f"Тикет <code>#{ticket_id}</code> создан — администратор рассмотрит ваш запрос.",
        hint="Переписка: «Подписка» → <b>Тикет возврата</b>.",
    )


def support_menu_text(tickets: list) -> str:
    open_count = len([t for t in tickets if t.get("category") != "refund"])
    status = (
        f"Открытых обращений: <b>{open_count}</b>"
        if open_count
        else "Открытых обращений нет — мы на связи."
    )
    return screen(
        "💬 <b>Поддержка</b>",
        status,
        hint="Создайте новое обращение или выберите тикет из списка.",
    )


def ticket_view_text(ticket: Dict[str, Any]) -> str:
    from db.tickets import category_label, STATUS_OPEN
    cat = category_label(ticket["category"])
    status = "открыт" if ticket.get("status") == STATUS_OPEN else "закрыт"
    lines = [
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
    hint = (
        "Нажмите «Начать переписку», чтобы написать администратору."
        if ticket.get("status") == STATUS_OPEN
        else None
    )
    return screen(f"🎫 <b>Тикет #{ticket['id']}</b>", "\n".join(lines), hint=hint)


def ticket_session_banner_text(ticket_id: int, category: str, *, is_new: bool = False) -> str:
    from db.tickets import category_label
    title = "🎫 <b>Новый тикет</b>" if is_new else "🔴 <b>Активная переписка</b>"
    return screen(
        title,
        f"Тикет <code>#{ticket_id}</code> · {category_label(category)}",
        "Отправляйте текст, фото или голосовые — всё дойдёт до администратора.",
        hint="«Завершить переписку» — выйти из режима (тикет останется открытым).",
    )


def ticket_created_text(ticket_id: int) -> str:
    return f"✅ Тикет <code>#{ticket_id}</code> создан — можно писать сообщения."


def refund_ticket_approved_user_text(ticket: Dict[str, Any]) -> str:
    ticket_id = ticket["id"]
    blocks = [
        f"Тикет <code>#{ticket_id}</code> закрыт.",
        "Возврат выполняется через платёжную систему.\n"
        "После подтверждения доступ к VPN скорректируется автоматически.\n"
        "Мы пришлём отдельное уведомление, когда возврат подтвердят.",
    ]
    if ticket.get("order_id"):
        blocks.append("\n".join([
            f"🧾 Заказ: <code>#{ticket['order_id']}</code>",
            f"📦 Тариф: <b>{ticket.get('plan_name') or '—'}</b>",
            f"💰 Сумма: <b>{ticket.get('order_amount') or '—'} ₽</b>",
        ]))
    return screen("✅ <b>Возврат одобрен</b>", *blocks)


def refund_ticket_rejected_user_text(ticket: Dict[str, Any]) -> str:
    ticket_id = ticket["id"]
    blocks = [
        f"Тикет <code>#{ticket_id}</code> закрыт.",
    ]
    if ticket.get("order_id"):
        blocks.append("\n".join([
            f"🧾 Заказ: <code>#{ticket['order_id']}</code>",
            f"📦 Тариф: <b>{ticket.get('plan_name') or '—'}</b>",
            f"💰 Сумма: <b>{ticket.get('order_amount') or '—'} ₽</b>",
        ]))
    return screen(
        "❌ <b>Возврат отклонён</b>",
        *blocks,
        hint="Если остались вопросы — напишите в поддержку.",
    )


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
        f"📅 Подписка до: {format_date(sub['end_date'])}",
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
        price_part = f"<s>{quote.base_price}</s> {money(quote.final_price)}"
    elif quote:
        price_part = money(quote.final_price)
    else:
        price_part = money(plan["price"])
    title = "⏳ <b>Ожидаем оплату</b> (тест)" if test_mode else "⏳ <b>Ожидаем оплату</b>"
    lines = [
        f"📦 {action}: <b>{plan['name']}</b> — {price_part}",
        f"💳 Способ: <b>{method_name}</b>",
    ]
    if status_note:
        lines.insert(0, f"⚠️ {status_note}")
    if expires_in:
        if expires_in == "00:00:00":
            lines.append("⏱ <b>Время оплаты истекло</b> — создайте новый заказ")
        else:
            lines.append(f"⏱ Истекает через: <b>{expires_in}</b>")
    else:
        lines.append("⏱ Окно оплаты: <b>30 минут</b> с момента создания счёта")
    if quote and quote.has_discount:
        lines.append(f"🎟 Промокод: <code>{quote.promo_code}</code>")
    renewal = renewal_hint(extend=extend, has_active_sub=has_active_sub)
    if renewal:
        lines.append(renewal)
    if test_mode:
        hint = (
            "<i>Тест: таймер ~30 мин, как у Platega.</i>\n"
            "Кнопки ниже симулируют проверку, оплату, webhook и отмену."
        )
    else:
        hint = (
            "После оплаты ключ выдаётся автоматически.\n"
            "Уже оплатили? Нажмите «Проверить оплату»."
        )
    return screen(title, "\n".join(lines), hint=hint)


def promo_enter_text() -> str:
    return screen(
        "🎟 <b>Промокод</b>",
        "• <b>Бесплатный тариф</b> — активируется сразу\n"
        "• <b>Скидка</b> — применится к ближайшей оплате в течение 7 дней",
        hint="Отправьте код следующим сообщением. Отмена: /start или «Главное меню».",
    )


def promo_applied_text(code: str, discount: int, final_price: int) -> str:
    return screen(
        f"✅ Промокод <code>{code}</code> применён",
        f"Скидка: <b>−{discount} ₽</b> · к оплате: {money(final_price)}",
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
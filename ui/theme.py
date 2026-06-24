"""Единая дизайн-система текстов и подписей кнопок VPN Bot."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Iterable, Optional

from config.plans import Plan

BRAND = "VPN Bot"
SEP = "────────────────"

# Подписи inline-кнопок
BTN_HOME = "🏠 Главное меню"
BTN_BACK = "◀️ Назад"
BTN_BACK_TARIFFS = "◀️ К тарифам"
BTN_PAY = "💳 Оплатить"
BTN_CHECK_PAY = "🔄 Проверить оплату"
BTN_SUPPORT = "💬 Написать в поддержку"
BTN_TRIAL = "🎁 Пробный период (3 дня)"
BTN_TARIFFS = "📦 Тарифы"
BTN_SUBSCRIPTION = "⚙️ Подписка"
BTN_PROMO = "🎟 Промокод"
BTN_SUPPORT_SHORT = "💬 Поддержка"
BTN_FAQ = "❓ FAQ"
BTN_SERVER_STATUS = "🌐 Доступность серверов"
BTN_POLICY = "📋 Политика проекта"
BTN_PRIVACY_POLICY = "📄 Политика конфиденциальности"
BTN_TERMS_OF_SERVICE = "📜 Пользовательское соглашение"
BTN_RESUME_PAY = "💳 Вернуться к оплате"


def screen(
    title: str,
    *blocks: str,
    hint: str | None = None,
    footer: str | None = None,
) -> str:
    """Собрать экран: заголовок, разделитель, блоки, подсказка."""
    lines = [title, SEP]
    for block in blocks:
        block = (block or "").strip()
        if block:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(block)
    if hint:
        lines += ["", f"<i>{hint}</i>"]
    if footer:
        lines += ["", footer]
    return "\n".join(lines)


DEFAULT_GREETING_TEMPLATE = "👋 Привет, <b>{name}</b>!{username_line}"


def render_greeting(
    template: Optional[str],
    first_name: Optional[str],
    username: Optional[str] | None = None,
) -> str:
    """Подставить {name}, {username}, {username_line} в шаблон приветствия."""
    tpl = (template or "").strip() or DEFAULT_GREETING_TEMPLATE
    name = html.escape(first_name or "друг")
    uname = html.escape(username or "")
    username_line = f" (@{uname})" if username else ""
    return (
        tpl.replace("{name}", name)
        .replace("{username}", uname)
        .replace("{username_line}", username_line)
    )


def user_chip(
    first_name: Optional[str],
    username: Optional[str] | None = None,
    *,
    template: Optional[str] = None,
) -> str:
    return render_greeting(template, first_name, username)


def money(amount: int | float) -> str:
    return f"<b>{int(amount)} ₽</b>"


def format_date(iso_date: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", ""))
        return dt.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date[:10]


def days_left(iso_date: str) -> int:
    try:
        end = datetime.fromisoformat(iso_date.replace("Z", ""))
        return max(0, (end - datetime.utcnow()).days)
    except ValueError:
        return 0


def traffic_label(gb: int) -> str:
    return "безлимит" if not gb else f"{gb} ГБ"


def price_per_month(plan: Plan) -> int:
    days = max(1, int(plan.get("days") or 1))
    return max(1, round(plan["price"] * 30 / days))


def plan_button_label(plan: Plan) -> str:
    ppm = price_per_month(plan)
    return f"📦 {plan['name']} · {plan['price']} ₽ · ~{ppm} ₽/мес"


def plan_specs_table(plan: Plan, *, quote_final: int | None = None) -> str:
    traffic = traffic_label(plan.get("traffic_gb", 0))
    price_line = money(quote_final if quote_final is not None else plan["price"])
    ppm = price_per_month(plan)
    return "\n".join([
        f"⏱ Срок: <b>{plan['days']} дн.</b>",
        f"📊 Трафик: {traffic}",
        f"💰 Цена: {price_line} · ~{ppm} ₽/мес",
    ])


def renewal_hint(*, extend: bool = False, has_active_sub: bool = False) -> str:
    if extend:
        return "Срок добавится к выбранной подписке."
    if has_active_sub:
        return "После выбора тарифа можно продлить текущую подписку или оформить новую."
    return ""


def bullet_list(items: Iterable[str]) -> str:
    return "\n".join(f"• {item}" for item in items if item)


def numbered_cards(blocks: list[str]) -> str:
    parts: list[str] = []
    for i, block in enumerate(blocks, 1):
        parts.append(f"<b>{i}.</b> {block.strip()}")
    return "\n\n".join(parts)


def error_screen(title: str, what: str, action: str) -> str:
    return screen(
        title,
        what,
        hint=action,
    )
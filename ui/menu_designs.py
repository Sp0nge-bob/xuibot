"""TEMP_MENU_DESIGN: переключатель макетов /start для проверки.

Потом вырезать: этот файл, bot/admin_debug_menu_design.py и хуки
с маркером TEMP_MENU_DESIGN (messages, handlers, admin_keyboards, bot/__init__).
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional

from config.trial import is_trial_email
from services.subscription_labels import subscription_display_name
from ui.theme import (
    SEP,
    brand_name,
    days_left,
    format_date,
    traffic_label,
    user_chip,
)

# id → короткое имя на кнопке отладки
DESIGNS: dict[str, str] = {
    "classic": "Классика",
    "quiet": "Тихий",
    "compact": "Компакт",
    "card": "Карточка",
    "ticket": "Билет",
    "quote": "Цитата",
    "chips": "Чипы",
}

CLASSIC = "classic"
SETTING_DEBUG_MENU_DESIGN = "debug_menu_design"

_MONTHS_RU = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def normalize_design_id(raw: Optional[str]) -> str:
    key = (raw or "").strip()
    return key if key in DESIGNS else CLASSIC


async def get_menu_design_id() -> str:
    """Текущий макет. Без ALLOW_DEBUG_ADMIN всегда классика."""
    from config.settings import settings

    if not settings.ALLOW_DEBUG_ADMIN:
        return CLASSIC
    from db.bot_settings import get_setting

    stored = await get_setting(SETTING_DEBUG_MENU_DESIGN)
    return normalize_design_id(stored)


async def set_menu_design_id(design_id: str) -> str:
    design_id = normalize_design_id(design_id)
    from db.bot_settings import delete_setting, set_setting

    if design_id == CLASSIC:
        await delete_setting(SETTING_DEBUG_MENU_DESIGN)
    else:
        await set_setting(SETTING_DEBUG_MENU_DESIGN, design_id)
    return design_id


def design_label(design_id: str) -> str:
    return DESIGNS.get(normalize_design_id(design_id), DESIGNS[CLASSIC])


def _days_ru(n: int) -> str:
    n = max(0, int(n))
    if 11 <= (n % 100) <= 14:
        word = "дней"
    else:
        rem = n % 10
        if rem == 1:
            word = "день"
        elif 2 <= rem <= 4:
            word = "дня"
        else:
            word = "дней"
    return f"{n} {word}"


def _format_date_long(iso_date: str) -> str:
    try:
        from utils.utc import parse_utc

        dt = parse_utc(iso_date)
        return f"{dt.day} {_MONTHS_RU[dt.month]} {dt.year}"
    except (ValueError, IndexError):
        return format_date(iso_date)


def _sub_title(sub: Dict[str, Any]) -> str:
    if is_trial_email(sub.get("client_email")):
        return "Пробная"
    return subscription_display_name(sub)


def _sub_fields(sub: Dict[str, Any]) -> dict[str, Any]:
    end_iso = sub.get("end_date") or ""
    return {
        "title": _sub_title(sub),
        "end": format_date(end_iso),
        "end_long": _format_date_long(end_iso),
        "left": days_left(end_iso),
        "traffic": traffic_label(sub.get("traffic_limit_gb", 0)),
    }


def _join(*blocks: str, hint: str | None = None, footer: str | None = None) -> str:
    lines: list[str] = []
    for block in blocks:
        block = (block or "").strip()
        if not block:
            continue
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(block)
    if hint:
        lines += ["", f"<i>{hint}</i>"]
    if footer:
        lines += ["", footer]
    return "\n".join(lines)


def _extra_before(
    *,
    announcement: Optional[str],
    refund_pending_chargeback: bool,
) -> list[str]:
    blocks: list[str] = []
    if announcement:
        blocks.append(announcement)
    if refund_pending_chargeback:
        from bot.messages import refund_pending_chargeback_notice

        blocks.append(refund_pending_chargeback_notice())
    return blocks


def _extra_after(
    *,
    pending_discount_promo: Optional[Dict[str, Any]],
    pending_discount_expires_at: Optional[str],
    pending_payment_plan_name: Optional[str],
) -> list[str]:
    blocks: list[str] = []
    if pending_discount_promo and pending_discount_expires_at:
        from bot.messages import _pending_discount_menu_lines

        blocks.append("\n".join(_pending_discount_menu_lines(
            pending_discount_promo, pending_discount_expires_at,
        )))
    if pending_payment_plan_name:
        blocks.append(
            f"⏳ <b>Незавершённая оплата</b>\n"
            f"   └ Тариф: <b>{pending_payment_plan_name}</b> — нажмите «Вернуться к оплате»"
        )
    return blocks


def _empty_sub(design_id: str) -> str:
    if design_id == "quiet":
        return "Подписки пока нет.\nМожно взять пробный период или выбрать тариф."
    if design_id == "compact":
        return "нет активной подписки"
    if design_id == "card":
        return "Подписка\n  нет активной"
    if design_id == "ticket":
        return "\n".join([
            f"{SEP}",
            "тариф     —",
            "статус    нет активной",
            f"{SEP}",
        ])
    if design_id == "quote":
        return "<blockquote>нет активной подписки</blockquote>"
    if design_id == "chips":
        return "нет активной подписки"
    return "Подписка: пока нет активной.\nМожно начать с пробного периода или выбрать тариф."


def _render_subs(design_id: str, subscriptions: List[Dict[str, Any]]) -> str:
    if not subscriptions:
        return _empty_sub(design_id)

    if design_id == "quiet":
        parts = []
        for sub in subscriptions:
            f = _sub_fields(sub)
            parts.append("\n".join([
                f"<b>{f['title']}</b> активна",
                f"до {f['end_long']}  ·  ещё {_days_ru(f['left'])}",
                f"трафик {f['traffic']}",
            ]))
        return "\n\n".join(parts)

    if design_id == "compact":
        parts = []
        for sub in subscriptions:
            f = _sub_fields(sub)
            parts.append(
                f"{f['title']}  ·  {f['traffic']}\n"
                f"до {f['end']}  ·  {f['left']} дн."
            )
        return "\n\n".join(parts)

    if design_id == "card":
        cards = []
        heading = "Подписка" if len(subscriptions) == 1 else "Подписки"
        cards.append(heading)
        for sub in subscriptions:
            f = _sub_fields(sub)
            cards.append(
                f"  {f['title']}\n"
                f"  до {f['end']}\n"
                f"  {_days_ru(f['left'])}  ·  {f['traffic']}"
            )
        return "\n\n".join(cards)

    if design_id == "ticket":
        tickets = []
        for sub in subscriptions:
            f = _sub_fields(sub)
            tickets.append("\n".join([
                SEP,
                f"тариф     {f['title']}",
                f"до        {f['end']}",
                f"осталось  {_days_ru(f['left'])}",
                f"трафик    {f['traffic']}",
                SEP,
            ]))
        return "\n".join(tickets)

    if design_id == "quote":
        quotes = []
        for sub in subscriptions:
            f = _sub_fields(sub)
            quotes.append(
                "<blockquote>"
                f"{f['title']}\n"
                f"до {f['end']} · {f['left']} дн. · {f['traffic']}"
                "</blockquote>"
            )
        return "\n".join(quotes)

    if design_id == "chips":
        chips = []
        for sub in subscriptions:
            f = _sub_fields(sub)
            chips.append("\n".join([
                f"📱 {f['title']}",
                f"⏱ {f['end']}   ·   {f['left']} дн.",
                f"∞  {f['traffic']}" if f["traffic"] == "безлимит"
                else f"📊 {f['traffic']}",
            ]))
        return "\n\n".join(chips)

    lines = []
    for sub in subscriptions:
        f = _sub_fields(sub)
        prefix = "🎁 Пробная" if is_trial_email(sub.get("client_email")) else f"📱 {f['title']}"
        lines.append(f"{prefix} · до <b>{f['end']}</b> · {f['left']} дн. · {f['traffic']}")
    if len(lines) == 1:
        return "📊 Ваша подписка:\n" + lines[0]
    return "📊 Ваши подписки:\n" + "\n".join(f"   └ {line}" for line in lines)


def render_alt_main_menu(
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
    test_mode: bool = False,
    design_id: str = CLASSIC,
) -> str:
    design_id = normalize_design_id(design_id)
    greeting = user_chip(first_name, username, template=greeting_template)
    before = _extra_before(
        announcement=announcement,
        refund_pending_chargeback=refund_pending_chargeback,
    )
    after = _extra_after(
        pending_discount_promo=pending_discount_promo,
        pending_discount_expires_at=pending_discount_expires_at,
        pending_payment_plan_name=pending_payment_plan_name,
    )
    sub = _render_subs(design_id, subscriptions)
    footer = "⚠️ <i>Тестовый режим включён</i>" if test_mode else None
    brand = brand_name()

    if design_id == "quiet":
        title = f"<b>{brand.upper()}</b>"
        return _join(title, greeting, *before, sub, *after, footer=footer)

    if design_id == "compact":
        who = html.escape((first_name or "друг").strip() or "друг")
        title = f"<b>{brand}</b>  ·  {who}"
        # компакт: имя уже в шапке, приветствие не дублируем
        return _join(title, *before, sub, *after, footer=footer)

    if design_id == "card":
        who = user_chip(
            first_name,
            username,
            template="<b>{name}</b>{username_line}",
        )
        title = f"<b>{brand}</b>"
        return _join(title, who, *before, sub, *after, footer=footer)

    if design_id == "ticket":
        who = html.escape((first_name or "друг").strip() or "друг")
        title = f"{SEP} {brand} {SEP}\nPASS  ·  {who}"
        return _join(title, *before, sub, *after, footer=footer)

    if design_id == "quote":
        title = f"<b>{brand}</b>"
        return _join(title, greeting, *before, sub, *after, footer=footer)

    if design_id == "chips":
        title = f"🌐 <b>{brand}</b>"
        return _join(title, greeting, *before, sub, *after, footer=footer)

    from ui.theme import screen

    return screen(
        f"🌐 <b>{brand}</b>",
        greeting,
        *before,
        sub,
        *after,
        hint="Выберите действие ниже 👇",
        footer=footer,
    )

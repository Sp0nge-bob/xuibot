"""Поиск подписок по названию («брат», «мама», «Подписка 3») или client_email (tg… / tgfree…)."""
from __future__ import annotations

import re

from config.trial import is_trial_email
from services.subscription_labels import subscription_display_name

_EMAIL_QUERY = re.compile(r"^tg(?:free)?\d+(?:_\d+)?$", re.I)
_DIGITS_SUFFIX = re.compile(r"^\d+(?:_\d+)?$")
_TRIAL_SHORT = re.compile(r"^free\d+(?:_\d+)?$", re.I)


def normalize_email_query(raw: str) -> str | None:
    q = (raw or "").strip().lower()
    if not q:
        return None
    if q.startswith("@"):
        q = q[1:]
    if _EMAIL_QUERY.match(q):
        return q
    if _DIGITS_SUFFIX.fullmatch(q):
        return f"tg{q}"
    if _TRIAL_SHORT.fullmatch(q):
        return f"tg{q}"
    return None


def match_subscription_by_email(
    subscriptions: list[dict],
    raw_query: str,
) -> dict | None:
    q = (raw_query or "").strip()
    if not q:
        return None
    q_lower = q.lower()

    # 1. Точное совпадение по названию подписки (или «пробная» для триала)
    for sub in subscriptions:
        disp = subscription_display_name(sub).strip().lower()
        if disp == q_lower:
            return sub
        if is_trial_email(sub.get("client_email")) and q_lower in ("пробная", "триал", "trial"):
            return sub

    # 2. Совпадение по части названия подписки
    for sub in subscriptions:
        disp = subscription_display_name(sub).strip().lower()
        if q_lower in disp:
            return sub
        if is_trial_email(sub.get("client_email")) and q_lower in "пробная подписка":
            return sub

    # 3. Fallback: поиск по техническому client_email (tg123456...)
    normalized = normalize_email_query(q)
    if normalized:
        for sub in subscriptions:
            if (sub.get("client_email") or "").lower() == normalized:
                return sub

    return None
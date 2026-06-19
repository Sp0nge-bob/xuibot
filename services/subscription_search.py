"""Поиск подписок по client_email (tg… / tgfree…)."""
from __future__ import annotations

import re

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
    normalized = normalize_email_query(raw_query)
    if not normalized:
        return None
    for sub in subscriptions:
        if (sub.get("client_email") or "").lower() == normalized:
            return sub
    return None
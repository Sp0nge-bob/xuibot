"""Пользовательские названия подписок для интерфейса бота."""
from __future__ import annotations

import re
from typing import Any

from config.trial import is_trial_email

_DISPLAY_NAME_MAX_LEN = 32
_DISPLAY_NAME_RE = re.compile(r"^[\w\s\-.!?()«»\"'№+#&@,:;]+$", re.UNICODE)


def subscription_display_name(sub: dict[str, Any]) -> str:
    name = (sub.get("display_name") or "").strip()
    if name:
        return name
    if is_trial_email(sub.get("client_email")):
        return "Пробная"
    return "Платная"


def subscription_short_label(sub: dict[str, Any]) -> str:
    kind = "🎁" if is_trial_email(sub.get("client_email")) else "📱"
    return f"{kind} {subscription_display_name(sub)}"


def normalize_display_name(raw: str) -> str | None:
    name = " ".join((raw or "").split())
    if not name or len(name) > _DISPLAY_NAME_MAX_LEN:
        return None
    if not _DISPLAY_NAME_RE.match(name):
        return None
    return name
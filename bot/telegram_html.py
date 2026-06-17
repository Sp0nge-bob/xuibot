"""Проверка и безопасная вставка HTML-фрагментов для Telegram parse_mode=HTML."""
from __future__ import annotations

import html
import re
from typing import Optional

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)(?:\s[^>]*)?>", re.IGNORECASE)

_TAG_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"b", "strong"}),
    frozenset({"i", "em"}),
    frozenset({"u", "ins"}),
    frozenset({"s", "strike", "del"}),
    frozenset({"code"}),
    frozenset({"pre"}),
    frozenset({"a"}),
    frozenset({"span"}),
    frozenset({"tg-spoiler"}),
)

_ALLOWED_TAGS = frozenset().union(*_TAG_GROUPS)


def _tag_group(tag: str) -> frozenset[str] | None:
    lowered = tag.lower()
    for group in _TAG_GROUPS:
        if lowered in group:
            return group
    return None


def validate_telegram_html(text: str) -> Optional[str]:
    """Возвращает текст ошибки или None, если фрагмент валиден для Telegram HTML."""
    stack: list[str] = []

    for match in _TAG_RE.finditer(text):
        closing, raw_tag = match.group(1), match.group(2)
        tag = raw_tag.lower()
        if tag not in _ALLOWED_TAGS:
            return f"Недопустимый тег &lt;{tag}&gt;. Разрешены: b, i, u, s, code, pre, a, span, tg-spoiler."

        group = _tag_group(tag)
        assert group is not None

        if closing:
            if not stack:
                return f"Лишний закрывающий тег &lt;/{tag}&gt;."
            if _tag_group(stack[-1]) != group:
                return (
                    f"Ожидался &lt;/{stack[-1]}&gt;, получен &lt;/{tag}&gt;. "
                    "Проверьте, что все теги закрыты в правильном порядке."
                )
            stack.pop()
        else:
            if stack and _tag_group(stack[-1]) == group:
                return (
                    f"Вместо &lt;{tag}&gt; нужен закрывающий тег "
                    f"&lt;/{stack[-1]}&gt; — со слэшем: <b>текст</b>."
                )
            stack.append(tag)

    if stack:
        unclosed = ", ".join(f"&lt;{tag}&gt;" for tag in reversed(stack))
        return f"Не закрыты теги: {unclosed}."

    return None


def safe_html_fragment(text: str) -> str:
    """Валидный HTML возвращает как есть, иначе экранирует спецсимволы."""
    if validate_telegram_html(text) is None:
        return text
    return html.escape(text)
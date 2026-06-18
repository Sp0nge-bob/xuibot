"""Проверка пользовательских текстов на требования Platega для VPN-проектов."""
from __future__ import annotations

import re
from typing import Optional

# Категория → шаблон (человекочитаемое имя для сообщения админу)
_FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"обход\s+\w*\s*блокир", re.I), "обход блокировок"),
    (re.compile(r"обход\s+(запрет|цензур|огранич|глуш)", re.I), "обход ограничений"),
    (re.compile(r"обойти\s+\w*\s*блокир", re.I), "обход блокировок"),
    (re.compile(r"глушил", re.I), "глушилки"),
    (re.compile(r"бел\w*\s+спис\w*", re.I), "белые списки"),
    (re.compile(r"(?<![A-Za-z])LTE(?![A-Za-z])", re.I), "LTE"),
    (re.compile(r"(?<![A-Za-z])4G(?![A-Za-z])", re.I), "мобильные сети (4G)"),
    (re.compile(r"(?<![A-Za-z])5G(?![A-Za-z])", re.I), "мобильные сети (5G)"),
]

COMPLIANCE_HINT = (
    "По требованиям Platega для VPN-проектов нельзя упоминать: "
    "обход блокировок, глушилки, белые списки, LTE/4G/5G и аналогичные формулировки."
)


def find_compliance_violation(text: str) -> Optional[str]:
    """Возвращает категорию нарушения или None."""
    if not (text or "").strip():
        return None
    for pattern, label in _FORBIDDEN:
        if pattern.search(text):
            return label
    return None


def compliance_error_message(text: str) -> Optional[str]:
    label = find_compliance_violation(text)
    if not label:
        return None
    return (
        f"❌ <b>Текст не соответствует требованиям Platega</b>\n\n"
        f"Обнаружено: <b>{label}</b>\n\n"
        f"{COMPLIANCE_HINT}"
    )
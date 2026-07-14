"""Команды с абсолютным приоритетом (обход ActionLock и FSM)."""
from __future__ import annotations

from aiogram.types import Message

from bot.admin_auth import is_admin


def _message_command(message: Message) -> str:
    text = (message.text or "").strip()
    if not text or not text.startswith("/"):
        return ""
    return text.split()[0].split("@")[0].lower()


def is_priority_reboot_message(message: Message) -> bool:
    """Админская /reboot — перебивает зависшие действия."""
    user = message.from_user
    if user is None or not is_admin(user.id):
        return False
    return _message_command(message) == "/reboot"
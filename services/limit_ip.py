"""Лимит одновременных IP (limitIp) в 3x-ui для trial и платных подписок."""
from __future__ import annotations

from config.trial import is_trial_email
from db import bot_settings as bot_settings_db


def format_connections_limit_line(limit: int) -> str:
    if limit <= 0:
        return "📱 Одновременных подключений: <b>без лимита</b>"
    return f"📱 Одновременных подключений: <b>{limit}</b>"


async def get_trial_limit_ip() -> int:
    return await bot_settings_db.get_trial_limit_ip()


async def get_paid_limit_ip() -> int:
    return await bot_settings_db.get_paid_limit_ip()


async def resolve_limit_ip_for_email(email: str) -> int:
    if is_trial_email(email):
        return await get_trial_limit_ip()
    return await get_paid_limit_ip()
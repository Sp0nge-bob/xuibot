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


async def apply_limit_ip_settings_on_primary(*, kind: str | None = None) -> dict[str, int]:
    """
    Обновить limitIp существующим клиентам только на основной ноде.
    Вторичные подтянет сама панель 3x-ui.
    kind: trial | paid | None (оба типа).
    """
    from loguru import logger

    from config.trial import is_trial_email
    from db import database as db
    from services.xui import update_client_limit_ip_on_primary

    trial_limit = await get_trial_limit_ip()
    paid_limit = await get_paid_limit_ip()
    stats = {"updated": 0, "skipped": 0, "missing": 0, "failed": 0}

    for sub in await db.get_all_active_subscriptions():
        email = str(sub.get("client_email") or "")
        if not email:
            continue
        is_trial = is_trial_email(email)
        if kind == "trial" and not is_trial:
            continue
        if kind == "paid" and is_trial:
            continue
        target = trial_limit if is_trial else paid_limit
        try:
            result = await update_client_limit_ip_on_primary(email, target)
            stats[result if result in stats else "failed"] += 1
        except Exception as e:
            stats["failed"] += 1
            logger.warning("limitIp primary update failed for {}: {}", email, e)

    logger.info(
        "limitIp on primary (kind={}): updated={} skipped={} missing={} failed={}",
        kind or "all",
        stats["updated"],
        stats["skipped"],
        stats["missing"],
        stats["failed"],
    )
    return stats
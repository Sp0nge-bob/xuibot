"""Админские операции с подписками."""
from typing import Any

from loguru import logger

from db import database as db
from services.xui import remove_client_everywhere


async def admin_delete_subscription(subscription_id: int) -> dict[str, Any]:
    sub = await db.get_subscription_by_id(subscription_id)
    if not sub:
        raise ValueError("Подписка не найдена")
    if not sub.get("is_active"):
        raise ValueError("Подписка уже неактивна")

    email = sub["client_email"]
    removed = await remove_client_everywhere(email)
    await db.deactivate_subscription(subscription_id)
    await db.cancel_refund_requests_for_subscription(subscription_id)

    logger.success(
        "Admin deleted subscription #{} ({}) from panel inbounds {}",
        subscription_id, email, removed,
    )
    return {
        "subscription_id": subscription_id,
        "tg_id": sub["tg_id"],
        "email": email,
        "removed_inbounds": removed,
    }
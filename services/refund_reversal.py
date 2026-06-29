"""Откат подписки при подтверждённом возврате оплаты (CHARGEBACKED)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from config.plans import get_plan
from db import database as db
from db import tickets as tickets_db
from services.node_sync import schedule_secondary_sync
from services.xui import (
    disable_client,
    extend_client,
    get_unified_panel_client,
    remove_client_everywhere,
)


async def _resolve_subscription(order: dict[str, Any]) -> dict[str, Any] | None:
    ticket = await tickets_db.get_refund_ticket_for_order(order["id"])
    if ticket and ticket.get("subscription_id"):
        sub = await db.get_subscription_by_id(ticket["subscription_id"])
        if sub:
            return sub

    if order.get("subscription_id"):
        sub = await db.get_subscription_by_id(order["subscription_id"])
        if sub:
            return sub

    sub = await db.get_subscription_by_order_id(order["id"])
    if sub:
        return sub

    if (order.get("order_type") or "new") == "new":
        return None

    return await db.get_primary_paid_subscription(order["tg_id"])


async def apply_refund_reversal(order: dict[str, Any]) -> dict[str, Any]:
    """
    Откатывает выдачу подписки после возврата средств.
    Новая покупка — удаление клиента; продление — сокращение срока на дни тарифа.
    """
    from services.referral import reverse_referral_rewards_for_order

    await reverse_referral_rewards_for_order(order)
    plan = get_plan(order.get("plan_id") or "")
    if not plan:
        logger.warning("Refund reversal skipped: unknown plan {}", order.get("plan_id"))
        return {"action": "skipped", "reason": "unknown_plan"}

    sub = await _resolve_subscription(order)
    if not sub:
        logger.warning("Refund reversal skipped: no subscription for order {}", order.get("id"))
        return {"action": "skipped", "reason": "no_subscription"}

    email = sub["client_email"]
    sub_id = sub["id"]
    full_revoke = sub.get("order_id") == order.get("id")

    if full_revoke:
        removed = await remove_client_everywhere(email)
        await db.deactivate_subscription(sub_id)
        schedule_secondary_sync(sub_id)
        logger.info(
            "Refund reversal: removed subscription #{} ({}) for order #{}",
            sub_id, email, order.get("id"),
        )
        return {
            "action": "revoked",
            "subscription_id": sub_id,
            "email": email,
            "removed_inbounds": removed,
        }

    new_end_iso, still_active = await db.shrink_subscription_record(sub_id, plan["days"])
    new_end = datetime.fromisoformat(new_end_iso.replace("Z", ""))
    new_expiry_ms = int(new_end.timestamp() * 1000)

    if still_active:
        if await get_unified_panel_client(email):
            await extend_client(email, plan["days"], target_expiry_ms=new_expiry_ms)
        schedule_secondary_sync(sub_id)
        logger.info(
            "Refund reversal: shortened subscription #{} to {} for order #{}",
            sub_id, new_end_iso[:10], order.get("id"),
        )
        return {
            "action": "shortened",
            "subscription_id": sub_id,
            "email": email,
            "end_date": new_end_iso[:10],
        }

    await disable_client(email)
    schedule_secondary_sync(sub_id)
    logger.info(
        "Refund reversal: disabled subscription #{} after shorten for order #{}",
        sub_id, order.get("id"),
    )
    return {
        "action": "disabled",
        "subscription_id": sub_id,
        "email": email,
        "end_date": new_end_iso[:10],
    }
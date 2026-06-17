"""Админские операции с подписками."""
from typing import Any

from loguru import logger

from config.trial import is_trial_email
from db import database as db
from db import tickets as tickets_db
from db import trial_grants as trial_db
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
    await tickets_db.cancel_tickets_for_subscription(subscription_id)

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


async def admin_reset_all_trials() -> dict[str, Any]:
    """Сброс всех активных пробных подписок и лимитов выдачи."""
    subs = await db.get_all_active_subscriptions()
    trial_subs = [s for s in subs if is_trial_email(s.get("client_email"))]
    removed_trials: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for sub in trial_subs:
        email = sub["client_email"]
        try:
            removed = await remove_client_everywhere(email)
            await db.deactivate_subscription(sub["id"])
            await tickets_db.cancel_tickets_for_subscription(sub["id"])
            removed_trials.append({
                "subscription_id": sub["id"],
                "tg_id": sub["tg_id"],
                "email": email,
                "removed_inbounds": removed,
            })
        except Exception as e:
            logger.error("Bulk trial reset failed for #{} ({}): {}", sub["id"], email, e)
            errors.append({
                "subscription_id": sub["id"],
                "tg_id": sub["tg_id"],
                "email": email,
                "error": str(e)[:200],
            })

    grants_deleted = await trial_db.reset_all_trial_grants()
    logger.info(
        "Admin reset ALL trials: removed={}, errors={}, grants_deleted={}",
        len(removed_trials), len(errors), grants_deleted,
    )
    return {
        "removed_trials": removed_trials,
        "errors": errors,
        "grants_deleted": grants_deleted,
    }


async def admin_reset_trial_for_user(tg_id: int) -> dict[str, Any]:
    """Сброс лимита пробного периода и деактивация активной пробной подписки."""
    removed_trials: list[dict[str, Any]] = []
    subs = await db.get_active_subscriptions(tg_id)
    for sub in subs:
        if not is_trial_email(sub.get("client_email")):
            continue
        email = sub["client_email"]
        removed = await remove_client_everywhere(email)
        await db.deactivate_subscription(sub["id"])
        await tickets_db.cancel_tickets_for_subscription(sub["id"])
        removed_trials.append({
            "subscription_id": sub["id"],
            "email": email,
            "removed_inbounds": removed,
        })

    grants_deleted = await trial_db.reset_trial_eligibility(tg_id)
    logger.info(
        "Admin reset trial for tg_id={}: grants_deleted={}, trials_removed={}",
        tg_id, grants_deleted, len(removed_trials),
    )
    return {
        "tg_id": tg_id,
        "grants_deleted": grants_deleted,
        "removed_trials": removed_trials,
    }
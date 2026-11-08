"""Отзыв grant-промокодов с сокращением/деактивацией подписки и уведомлением пользователя."""
from __future__ import annotations

from typing import Any, Optional
from loguru import logger

from config.plans import get_plan
from db import database as db
from db import promo_codes as promo_db
from services.node_sync import schedule_secondary_sync
from services.xui import disable_client, extend_client
from utils.utc import utc_iso_to_ms


async def revoke_grant_promo_use(
    use_id: int,
    *,
    admin_tg_id: Optional[int] = None,
    bot_instance: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Отозвать активацию grant-промокода:
    1. Уменьшить grant_bonus_days и сократить срок подписки на дни тарифа.
    2. Если срок истёк или подписка чисто бонусная — отключить клиента на 3x-ui и деактивировать подписку.
    3. Пометить promo_uses как is_revoked=1, уменьшить used_count в promo_codes.
    4. Отправить уведомление пользователю в Telegram.
    """
    use = await promo_db.get_promo_use_by_id(use_id)
    if not use:
        raise ValueError("Запись об активации промокода не найдена")
    if use.get("is_revoked"):
        raise ValueError("Активация этого промокода уже была отозвана")

    promo_id = int(use["promo_id"])
    promo = await promo_db.get_promo_by_id(promo_id)
    plan_id = promo_db.grant_plan_id(promo) if promo else None
    if not plan_id and use.get("plan_ids"):
        plan_id = str(use["plan_ids"]).split(",")[0].strip() or None

    plan = get_plan(plan_id or "") if plan_id else None
    grant_days = int(plan["days"]) if plan and plan.get("days") else 30

    sub_id = use.get("subscription_id")
    sub = await db.get_subscription_by_id(int(sub_id)) if sub_id else None

    action_taken = "none"
    still_active = False
    new_end_iso = None

    if sub:
        email = str(sub.get("client_email") or "")
        paid_orders = await db.get_paid_orders_for_subscription(sub["id"], limit=1)
        full_revoke = (sub.get("order_id") is None and not paid_orders)

        await db.subtract_grant_bonus_days(sub["id"], grant_days)
        new_end_iso, still_active = await db.shrink_subscription_record(sub["id"], grant_days)

        if not still_active or full_revoke:
            await db.deactivate_subscription(sub["id"])
            if email:
                await disable_client(email)
            schedule_secondary_sync(sub["id"])
            action_taken = "deactivated"
        else:
            if email:
                new_expiry_ms = utc_iso_to_ms(new_end_iso)
                await extend_client(email, 0, target_expiry_ms=new_expiry_ms)
            schedule_secondary_sync(sub["id"])
            action_taken = "shortened"

    await promo_db.mark_promo_use_revoked(use_id)
    await promo_db.decrement_promo_used_count(promo_id)

    code_name = use.get("code") or "—"
    tg_id = int(use["tg_id"])
    logger.info(
        "Admin {} revoked grant use_id={} (code={}, tg_id={}, action={})",
        admin_tg_id, use_id, code_name, tg_id, action_taken,
    )

    if bot_instance and tg_id:
        try:
            if action_taken == "deactivated":
                msg = (
                    f"⚠️ <b>Внимание!</b>\n\n"
                    f"Тариф по промокоду <code>{code_name}</code> был отозван администратором.\n"
                    f"Ваша подписка деактивирована."
                )
            elif action_taken == "shortened" and new_end_iso:
                from utils.utc import parse_utc
                end_date_str = parse_utc(new_end_iso).strftime("%d.%m.%Y")
                msg = (
                    f"⚠️ <b>Внимание!</b>\n\n"
                    f"Бонусный период по промокоду <code>{code_name}</code> был отозван администратором.\n"
                    f"Срок действия вашей подписки скорректирован до <b>{end_date_str}</b>."
                )
            else:
                msg = (
                    f"⚠️ <b>Внимание!</b>\n\n"
                    f"Бонус по промокоду <code>{code_name}</code> был отозван администратором."
                )
            await bot_instance.send_message(chat_id=tg_id, text=msg)
        except Exception as e:
            logger.warning("Failed to send revocation notice to tg_id={}: {}", tg_id, e)

    return {
        "success": True,
        "use_id": use_id,
        "promo_id": promo_id,
        "code": code_name,
        "tg_id": tg_id,
        "action": action_taken,
        "grant_days": grant_days,
        "still_active": still_active,
        "new_end_date": new_end_iso,
    }

"""Активация промокодов на бесплатный тариф."""
from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from config.plans import Plan, get_plan
from services.subscription_labels import subscription_short_label
from ui.theme import format_date, screen, traffic_label
from db import promo_codes as promo_db
from services.fulfillment import FulfillmentResult, fulfill_plan_for_tg
from services.pricing import validate_grant_promo

GrantPromoMode = Literal["extend", "new"]


def grant_promo_choice_text(promo: dict, plan: Plan, paid_subs: list[dict[str, Any]]) -> str:
    traffic = traffic_label(plan.get("traffic_gb", 0))
    lines = [
        f"🎟 Код: <code>{promo['code']}</code>",
        f"🎁 Тариф: <b>{plan['days']} дн.</b> · {traffic}",
        "",
        "У вас уже есть <b>активная платная подписка</b>:",
    ]
    for sub in paid_subs:
        lines.append(
            f"• {subscription_short_label(sub)} — до {format_date(sub['end_date'])}"
        )
    return screen(
        "🎟 <b>Промокод принят</b>",
        "\n".join(lines),
        hint="Продлить одну из подписок или получить новую бесплатную?",
    )


def grant_promo_extend_picker_text(subs: list[dict[str, Any]]) -> str:
    lines = [f"• {subscription_short_label(sub)}" for sub in subs]
    return screen(
        "🔄 <b>Продление промокодом</b>",
        "Выберите, какую подписку продлить:",
        "\n".join(lines),
    )


async def fulfill_grant_promo(
    tg_id: int,
    promo_id: int,
    *,
    mode: GrantPromoMode,
    subscription_id: int | None = None,
) -> FulfillmentResult:
    """Применить grant-промокод после выбора пользователя (или сразу, если платной подписки нет)."""
    promo = await promo_db.get_promo_by_id(promo_id)
    if not promo:
        raise ValueError("Промокод не найден")

    _, err = await validate_grant_promo(promo["code"], tg_id=tg_id)
    if err:
        raise ValueError(err)

    plan_id = promo_db.grant_plan_id(promo)
    plan = get_plan(plan_id or "")
    if not plan:
        raise ValueError("Тариф промокода не найден")

    from db import database as db

    if mode == "new":
        result = await fulfill_plan_for_tg(
            tg_id,
            plan,
            order_id=None,
            order_type="new",
            subscription_id=None,
            sub_display_name=None,
            title_new="Промокод активирован!",
            title_extend="Промокод применён — подписка продлена!",
            log_context=f"Grant promo {promo['code']} (new sub)",
        )
    else:
        target_sub = None
        if subscription_id:
            target_sub = await db.get_subscription_by_id(subscription_id)
            if (
                not target_sub
                or target_sub["tg_id"] != tg_id
                or not target_sub.get("is_active")
            ):
                target_sub = None
        if not target_sub:
            target_sub = await db.get_primary_paid_subscription(tg_id)
        if not target_sub:
            raise ValueError("Нет активной платной подписки для продления")

        result = await fulfill_plan_for_tg(
            tg_id,
            plan,
            order_id=None,
            order_type="extend",
            subscription_id=target_sub["id"],
            sub_display_name=None,
            title_new="Промокод активирован!",
            title_extend="Промокод применён — подписка продлена!",
            log_context=f"Grant promo {promo['code']} (extend #{target_sub['id']})",
        )

    await promo_db.record_grant_promo_use(promo["id"], tg_id)
    logger.info("Grant promo {} redeemed by tg_id={} mode={}", promo["code"], tg_id, mode)
    return result
"""Активация промокодов на бесплатный тариф."""
from loguru import logger

from config.plans import get_plan
from db import promo_codes as promo_db
from services.fulfillment import FulfillmentResult, fulfill_plan_for_tg
from services.pricing import validate_grant_promo


async def redeem_grant_promo(tg_id: int, code: str) -> FulfillmentResult:
    promo, err = await validate_grant_promo(code, tg_id=tg_id)
    if err:
        raise ValueError(err)

    plan_id = promo_db.grant_plan_id(promo)
    plan = get_plan(plan_id or "")
    if not plan:
        raise ValueError("Тариф промокода не найден")

    result = await fulfill_plan_for_tg(
        tg_id,
        plan,
        order_id=None,
        title_new="Промокод активирован!",
        title_extend="Промокод применён — подписка продлена!",
        log_context=f"Grant promo {promo['code']}",
    )
    await promo_db.record_grant_promo_use(promo["id"], tg_id)
    logger.info("Grant promo {} redeemed by tg_id={}", promo["code"], tg_id)
    return result
"""Единая активация промокода из главного меню."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db.promo_codes import is_grant_promo
from services.fulfillment import FulfillmentResult
from services.grant_promo import redeem_grant_promo
from services.pricing import _validate_promo_common, calc_discount


@dataclass
class PromoRedeemResult:
    kind: str
    fulfillment: Optional[FulfillmentResult] = None
    message: Optional[str] = None


def _discount_label(promo: dict) -> str:
    if promo["discount_type"] == "percent":
        return f"{promo['discount_value']}%"
    return f"{promo['discount_value']} ₽"


async def redeem_promo_code(tg_id: int, code: str) -> PromoRedeemResult:
    promo = await promo_db.get_promo_by_code(code)
    if not promo:
        raise ValueError("Промокод не найден")

    if is_grant_promo(promo):
        fulfillment = await redeem_grant_promo(tg_id, code)
        return PromoRedeemResult(kind="grant", fulfillment=fulfillment)

    err = await _validate_promo_common(promo, tg_id=tg_id)
    if err:
        raise ValueError(err)

    await promo_db.record_grant_promo_use(promo["id"], tg_id)
    row = await pending_db.set_pending_discount(tg_id, promo)
    expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", ""))
    allowed = (promo.get("plan_ids") or "").strip()
    plans_hint = (
        f"Тарифы: <code>{allowed}</code>"
        if allowed
        else "Действует на <b>любой</b> тариф"
    )
    message = (
        "✅ <b>Промокод активирован!</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"🎟 Код: <code>{promo['code']}</code>\n"
        f"💰 Скидка: <b>{_discount_label(promo)}</b>\n"
        f"{plans_hint}\n\n"
        f"Скидка применится к <b>ближайшей успешной оплате</b> "
        f"до <b>{expires.strftime('%d.%m.%Y %H:%M')} UTC</b>.\n\n"
        "Перейдите в «Тарифы» и оформите подписку — цена будет с учётом скидки."
    )
    return PromoRedeemResult(kind="discount", message=message)
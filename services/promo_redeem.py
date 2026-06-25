"""Единая активация промокода из главного меню."""
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.settings import settings
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db.promo_codes import is_grant_promo
from services.fulfillment import FulfillmentResult
from services.grant_promo import fulfill_grant_promo
from services.pricing import _validate_promo_common, calc_discount


@dataclass
class PromoRedeemResult:
    kind: str
    fulfillment: Optional[FulfillmentResult] = None
    message: Optional[str] = None
    promo_id: Optional[int] = None


def _discount_label(promo: dict) -> str:
    if promo["discount_type"] == "percent":
        return f"{promo['discount_value']}%"
    return f"{promo['discount_value']} ₽"


_last_redeem_by_tg: dict[int, float] = {}


def _promo_redeem_rate_limited(tg_id: int) -> bool:
    cooldown = float(settings.PROMO_REDEEM_COOLDOWN_SEC)
    if cooldown <= 0:
        return False
    now = time.monotonic()
    last = _last_redeem_by_tg.get(tg_id, 0.0)
    if now - last < cooldown:
        return True
    _last_redeem_by_tg[tg_id] = now
    if len(_last_redeem_by_tg) > 10_000:
        stale = [k for k, ts in _last_redeem_by_tg.items() if now - ts > cooldown * 20]
        for k in stale:
            _last_redeem_by_tg.pop(k, None)
    return False


async def redeem_promo_code(tg_id: int, code: str) -> PromoRedeemResult:
    if _promo_redeem_rate_limited(tg_id):
        raise ValueError("Подождите несколько секунд перед следующей попыткой")
    promo = await promo_db.get_promo_by_code(code)
    if not promo:
        raise ValueError("Промокод не найден")

    if is_grant_promo(promo):
        from config.plans import get_plan
        from db import database as db
        from services.grant_promo import grant_promo_choice_text

        err = await _validate_promo_common(promo, tg_id=tg_id)
        if err:
            raise ValueError(err)
        plan_id = promo_db.grant_plan_id(promo)
        plan = get_plan(plan_id or "")
        if not plan:
            raise ValueError("Тариф промокода не настроен")

        paid_subs = await db.get_active_paid_subscriptions(tg_id)
        if paid_subs:
            return PromoRedeemResult(
                kind="grant_choice",
                message=grant_promo_choice_text(promo, plan, paid_subs),
                promo_id=int(promo["id"]),
            )

        fulfillment = await fulfill_grant_promo(tg_id, int(promo["id"]), mode="new")
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
        "Перейдите в «Покупка» и оформите подписку — цена будет с учётом скидки."
    )
    return PromoRedeemResult(kind="discount", message=message)
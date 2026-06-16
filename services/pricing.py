"""Расчёт цен тарифов и применение промокодов."""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from config.plans import Plan
from db.plan_prices import get_all_effective_plans, get_effective_plan
from db import promo_codes as promo_db


@dataclass
class PriceQuote:
    plan: Plan
    base_price: int
    final_price: int
    discount_amount: int
    promo_code: Optional[str] = None
    promo_id: Optional[int] = None

    @property
    def has_discount(self) -> bool:
        return self.discount_amount > 0


def calc_discount(base_price: int, discount_type: str, discount_value: int) -> int:
    if discount_type == "percent":
        return min(base_price, base_price * discount_value // 100)
    return min(base_price, discount_value)


async def get_plan_quote(
    plan_id: str,
    *,
    promo_code: Optional[str] = None,
    tg_id: Optional[int] = None,
) -> Optional[PriceQuote]:
    plan = await get_effective_plan(plan_id)
    if not plan:
        return None

    base_price = plan["price"]
    final_price = base_price
    discount_amount = 0
    promo_id = None
    applied_code = None

    if promo_code and tg_id is not None:
        promo, err = await validate_promo(promo_code, plan_id=plan_id, tg_id=tg_id)
        if promo:
            discount_amount = calc_discount(
                base_price, promo["discount_type"], promo["discount_value"],
            )
            final_price = max(0, base_price - discount_amount)
            promo_id = promo["id"]
            applied_code = promo["code"]

    plan_out = {**plan, "price": final_price}
    return PriceQuote(
        plan=plan_out,
        base_price=base_price,
        final_price=final_price,
        discount_amount=discount_amount,
        promo_code=applied_code,
        promo_id=promo_id,
    )


async def validate_promo(
    code: str,
    *,
    plan_id: str,
    tg_id: int,
) -> tuple[Optional[dict], Optional[str]]:
    promo = await promo_db.get_promo_by_code(code)
    if not promo:
        return None, "Промокод не найден"
    if not promo.get("is_active"):
        return None, "Промокод отключён"

    valid_until = promo.get("valid_until")
    if valid_until:
        try:
            if datetime.fromisoformat(valid_until.replace("Z", "")) < datetime.utcnow():
                return None, "Срок действия промокода истёк"
        except ValueError:
            pass

    max_uses = promo.get("max_uses")
    if max_uses is not None and (promo.get("used_count") or 0) >= max_uses:
        return None, "Промокод исчерпан"

    per_user = promo.get("per_user_limit")
    if per_user and per_user > 0:
        user_uses = await promo_db.count_user_promo_uses(promo["id"], tg_id)
        if user_uses >= per_user:
            if per_user == 1:
                return None, "Вы уже использовали этот промокод"
            return None, f"Лимит промокода для вас исчерпан ({per_user} раз)"

    allowed_raw = (promo.get("plan_ids") or "").strip()
    if allowed_raw:
        allowed = {x.strip() for x in allowed_raw.split(",") if x.strip()}
        if plan_id not in allowed:
            return None, "Промокод не действует на этот тариф"

    return promo, None


async def list_plans() -> List[Plan]:
    return await get_all_effective_plans()


async def apply_promo_on_paid_order(order: dict) -> None:
    promo_code = order.get("promo_code")
    if not promo_code or not order.get("id"):
        return
    if await promo_db.has_order_promo_use(order["id"]):
        return
    promo = await promo_db.get_promo_by_code(promo_code)
    if not promo:
        return
    await promo_db.record_promo_use(promo["id"], order["tg_id"], order["id"])
"""Расчёт цен тарифов и применение промокодов."""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from config.plans import Plan, get_plan
from db.plan_prices import get_all_effective_plans, get_effective_plan
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db.promo_codes import is_grant_promo


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


def quote_from_order(order: dict, plan: Plan) -> PriceQuote:
    """Цена из сохранённого заказа (сумма счёта Platega), не из текущих настроек."""
    final_price = int(order.get("amount") or plan["price"])
    base_price = int(order.get("original_amount") or final_price)
    discount_amount = int(order.get("discount_amount") or 0)
    if discount_amount <= 0 and base_price > final_price:
        discount_amount = base_price - final_price
    promo_code = order.get("promo_code") or None
    return PriceQuote(
        plan={**plan, "price": final_price},
        base_price=base_price,
        final_price=final_price,
        discount_amount=discount_amount,
        promo_code=promo_code,
    )


def _promo_plan_allowed(promo: dict, plan_id: str) -> bool:
    allowed_raw = (promo.get("plan_ids") or "").strip()
    if not allowed_raw:
        return True
    allowed = {x.strip() for x in allowed_raw.split(",") if x.strip()}
    return plan_id in allowed


async def _validate_promo_common(
    promo: dict,
    *,
    tg_id: int,
) -> Optional[str]:
    if not promo.get("is_active"):
        return "Промокод отключён"

    valid_until = promo.get("valid_until")
    if valid_until:
        try:
            if datetime.fromisoformat(valid_until.replace("Z", "")) < datetime.utcnow():
                return "Срок действия промокода истёк"
        except ValueError:
            pass

    max_uses = promo.get("max_uses")
    if max_uses is not None and (promo.get("used_count") or 0) >= max_uses:
        return "Промокод исчерпан"

    per_user = promo.get("per_user_limit")
    if per_user and per_user > 0:
        user_uses = await promo_db.count_user_promo_uses(promo["id"], tg_id)
        if user_uses >= per_user:
            if per_user == 1:
                return "Вы уже использовали этот промокод"
            return f"Лимит промокода для вас исчерпан ({per_user} раз)"

    return None


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

    effective_code = promo_code
    from_pending = False
    if not effective_code and tg_id is not None:
        pending = await pending_db.get_active_pending_discount(tg_id)
        if pending:
            effective_code = pending["promo_code"]
            from_pending = True

    if effective_code and tg_id is not None:
        promo = await promo_db.get_promo_by_code(effective_code)
        if promo and not is_grant_promo(promo):
            if from_pending:
                if _promo_plan_allowed(promo, plan_id):
                    discount_amount = calc_discount(
                        base_price, promo["discount_type"], promo["discount_value"],
                    )
                    final_price = max(0, base_price - discount_amount)
                    promo_id = promo["id"]
                    applied_code = promo["code"]
            else:
                promo_valid, err = await validate_promo(
                    effective_code, plan_id=plan_id, tg_id=tg_id,
                )
                if promo_valid:
                    discount_amount = calc_discount(
                        base_price, promo_valid["discount_type"], promo_valid["discount_value"],
                    )
                    final_price = max(0, base_price - discount_amount)
                    promo_id = promo_valid["id"]
                    applied_code = promo_valid["code"]

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
    if is_grant_promo(promo):
        return None, "Этот промокод выдаёт тариф бесплатно — активируйте его в главном меню → «Промокоды»."

    err = await _validate_promo_common(promo, tg_id=tg_id)
    if err:
        return None, err

    if not _promo_plan_allowed(promo, plan_id):
        return None, "Промокод не действует на этот тариф"

    return promo, None


async def validate_grant_promo(
    code: str,
    *,
    tg_id: int,
) -> tuple[Optional[dict], Optional[str]]:
    promo = await promo_db.get_promo_by_code(code)
    if not promo:
        return None, "Промокод не найден"
    if not is_grant_promo(promo):
        return None, "Этот промокод даёт скидку — активируйте его в главном меню → «Промокоды»"

    err = await _validate_promo_common(promo, tg_id=tg_id)
    if err:
        return None, err

    plan_id = promo_db.grant_plan_id(promo)
    if not plan_id or not get_plan(plan_id):
        return None, "Тариф промокода не настроен"

    return promo, None


async def list_plans() -> List[Plan]:
    return await get_all_effective_plans()


async def apply_promo_on_paid_order(order: dict) -> None:
    promo_code = order.get("promo_code")
    if not promo_code or not order.get("id"):
        return
    await pending_db.consume_pending_discount(
        order["tg_id"], order["id"], promo_code,
    )
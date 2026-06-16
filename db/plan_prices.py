"""Цены тарифов — переопределения в SQLite (дефолты из config/plans.py)."""
import json
from typing import Dict, List, Optional

from config.plans import PLANS, Plan, get_plan
from db.bot_settings import get_setting, set_setting

SETTING_PLAN_PRICES = "plan_prices"


async def get_price_overrides() -> Dict[str, int]:
    raw = await get_setting(SETTING_PLAN_PRICES)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float, str))}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


async def set_price_overrides(overrides: Dict[str, int]) -> None:
    await set_setting(SETTING_PLAN_PRICES, json.dumps(overrides, ensure_ascii=False))


async def get_plan_price(plan_id: str) -> Optional[int]:
    overrides = await get_price_overrides()
    if plan_id in overrides:
        return overrides[plan_id]
    base = get_plan(plan_id)
    return base["price"] if base else None


async def set_plan_price(plan_id: str, price: int) -> int:
    if not get_plan(plan_id):
        raise ValueError(f"Неизвестный тариф: {plan_id}")
    if price < 0:
        raise ValueError("Цена не может быть отрицательной")
    overrides = await get_price_overrides()
    overrides[plan_id] = price
    await set_price_overrides(overrides)
    return price


async def get_effective_plan(plan_id: str) -> Optional[Plan]:
    base = get_plan(plan_id)
    if not base:
        return None
    price = await get_plan_price(plan_id)
    return {
        **base,
        "price": price if price is not None else base["price"],
        "default_price": base["price"],
    }


async def get_all_effective_plans() -> List[Plan]:
    plans: List[Plan] = []
    for base in PLANS:
        plan = await get_effective_plan(base["id"])
        if plan:
            plans.append(plan)
    return plans
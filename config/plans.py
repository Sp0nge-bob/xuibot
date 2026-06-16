"""
Планы подписок. Легко редактировать.
Можно вынести в plans.json при желании.
"""

from typing import TypedDict, List

class Plan(TypedDict):
    id: str
    name: str          # Отображаемое название
    days: int          # Длительность в днях
    price: int         # Цена в рублях (или другой валюте Platega)
    traffic_gb: int    # 0 = безлимит. Иначе лимит в ГБ (py3xui принимает байты)

PLANS: List[Plan] = [
    {
        "id": "1m",
        "name": "1 месяц",
        "days": 30,
        "price": 300,
        "traffic_gb": 0,
    },
    {
        "id": "3m",
        "name": "3 месяца",
        "days": 90,
        "price": 750,
        "traffic_gb": 0,
    },
    {
        "id": "6m",
        "name": "6 месяцев",
        "days": 180,
        "price": 1350,
        "traffic_gb": 0,
    },
    {
        "id": "12m",
        "name": "12 месяцев",
        "days": 365,
        "price": 2500,
        "traffic_gb": 0,
    },
]

def get_plan(plan_id: str) -> Plan | None:
    for p in PLANS:
        if p["id"] == plan_id:
            return p
    return None

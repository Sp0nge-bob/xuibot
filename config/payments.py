"""Способы оплаты Platega (ID уточняйте у менеджера, значения по умолчанию — из документации)."""
from typing import TypedDict, List, Optional


class PaymentMethod(TypedDict):
    key: str
    name: str
    emoji: str
    platega_id: int


def get_payment_methods(sbp_id: int, crypto_id: int) -> List[PaymentMethod]:
    return [
        {"key": "sbp", "name": "СБП", "emoji": "🏦", "platega_id": sbp_id},
        {"key": "crypto", "name": "Криптовалюта", "emoji": "₿", "platega_id": crypto_id},
    ]


def get_payment_method_by_key(
    key: str,
    sbp_id: int,
    crypto_id: int,
) -> Optional[PaymentMethod]:
    for m in get_payment_methods(sbp_id, crypto_id):
        if m["key"] == key:
            return m
    return None


def get_payment_method_by_platega_id(
    platega_id: int,
    sbp_id: int,
    crypto_id: int,
) -> Optional[PaymentMethod]:
    for m in get_payment_methods(sbp_id, crypto_id):
        if m["platega_id"] == platega_id:
            return m
    return None
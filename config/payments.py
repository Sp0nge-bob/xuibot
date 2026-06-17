"""Способы оплаты Platega (ID — docs.platega.io, переопределение в .env)."""
from typing import List, Optional, TypedDict

from config.settings import settings


class PaymentMethod(TypedDict):
    key: str
    name: str
    emoji: str
    platega_id: int


_METHOD_META: list[tuple[str, str, str, str]] = [
    ("sbp", "СБП (QR)", "🏦", "PLATEGA_SBP_METHOD"),
    ("erip", "ЕРИП", "🏛", "PLATEGA_ERIP_METHOD"),
    ("card", "Банковская карта", "💳", "PLATEGA_CARD_METHOD"),
    ("intl", "Международная оплата", "🌍", "PLATEGA_INTL_METHOD"),
    ("crypto", "Криптовалюта", "₿", "PLATEGA_CRYPTO_METHOD"),
]

_DEFAULT_ENABLED: dict[str, bool] = {
    "sbp": True,
    "erip": False,
    "card": False,
    "intl": False,
    "crypto": True,
}


def default_payment_methods_enabled() -> dict[str, bool]:
    return dict(_DEFAULT_ENABLED)


def all_payment_method_definitions() -> List[PaymentMethod]:
    """Все методы из API Platega с актуальными platega_id из settings."""
    methods: List[PaymentMethod] = []
    for key, name, emoji, setting_name in _METHOD_META:
        platega_id = int(getattr(settings, setting_name))
        methods.append({
            "key": key,
            "name": name,
            "emoji": emoji,
            "platega_id": platega_id,
        })
    return methods


def get_payment_method_by_key(key: str) -> Optional[PaymentMethod]:
    for m in all_payment_method_definitions():
        if m["key"] == key:
            return m
    return None


def get_payment_method_by_platega_id(platega_id: int) -> Optional[PaymentMethod]:
    for m in all_payment_method_definitions():
        if m["platega_id"] == platega_id:
            return m
    return None


def filter_payment_methods(
    methods: List[PaymentMethod],
    enabled: dict[str, bool],
) -> List[PaymentMethod]:
    return [m for m in methods if enabled.get(m["key"], False)]


# Обратная совместимость (устарело — используйте all_payment_method_definitions)
def get_payment_methods(sbp_id: int, crypto_id: int) -> List[PaymentMethod]:
    del sbp_id, crypto_id
    return all_payment_method_definitions()
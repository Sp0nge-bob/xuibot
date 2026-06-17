"""Включение/отключение способов оплаты (хранится в bot_settings)."""
from __future__ import annotations

import json
from typing import Dict, List


from config.payments import (
    PaymentMethod,
    all_payment_method_definitions,
    default_payment_methods_enabled,
    filter_payment_methods,
    get_payment_method_by_key,
)
from db.connection import get_db

SETTING_PAYMENT_METHODS_ENABLED = "payment_methods_enabled"


def _normalize_enabled(raw: dict | None) -> dict[str, bool]:
    defaults = default_payment_methods_enabled()
    if not raw:
        return defaults
    result = dict(defaults)
    for key in defaults:
        if key in raw:
            result[key] = bool(raw[key])
    return result


async def get_payment_methods_enabled() -> dict[str, bool]:
    async with get_db() as db:
        async with db.execute(
            "SELECT value FROM bot_settings WHERE key = ?",
            (SETTING_PAYMENT_METHODS_ENABLED,),
        ) as cur:
            row = await cur.fetchone()
    if not row or not row[0]:
        return default_payment_methods_enabled()
    try:
        data = json.loads(row[0])
        if isinstance(data, dict):
            return _normalize_enabled(data)
    except (json.JSONDecodeError, TypeError):
        pass
    return default_payment_methods_enabled()


async def set_payment_methods_enabled(enabled: dict[str, bool]) -> dict[str, bool]:
    normalized = _normalize_enabled(enabled)
    if not any(normalized.values()):
        raise ValueError("Должен быть включён хотя бы один способ оплаты")
    payload = json.dumps(normalized, ensure_ascii=False)
    async with get_db() as db:
        await db.execute(
            """INSERT INTO bot_settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = CURRENT_TIMESTAMP""",
            (SETTING_PAYMENT_METHODS_ENABLED, payload),
        )
        await db.commit()
    return normalized


async def toggle_payment_method(key: str) -> dict[str, bool]:
    method = get_payment_method_by_key(key)
    if not method:
        raise ValueError(f"Неизвестный способ оплаты: {key}")
    enabled = await get_payment_methods_enabled()
    new_value = not enabled.get(key, False)
    if not new_value:
        other_on = any(v for k, v in enabled.items() if k != key and v)
        if not other_on:
            raise ValueError("Нельзя отключить последний способ оплаты")
    enabled[key] = new_value
    return await set_payment_methods_enabled(enabled)


async def get_enabled_payment_methods() -> List[PaymentMethod]:
    enabled = await get_payment_methods_enabled()
    return filter_payment_methods(all_payment_method_definitions(), enabled)


async def is_payment_method_enabled(key: str) -> bool:
    enabled = await get_payment_methods_enabled()
    return bool(enabled.get(key, False))
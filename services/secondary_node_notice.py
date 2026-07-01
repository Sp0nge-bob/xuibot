"""Приписка для пользователей, когда недоступна вторичная нода."""
from __future__ import annotations

import time

from db import xui_nodes as nodes_db

SECONDARY_NODE_NOTICE = (
    "⚠️ <i>Один из подключенных серверов в данный момент недоступен</i>"
)

_cached: bool = False
_checked_at: float = 0.0


async def has_unhealthy_secondary_node(*, max_age_sec: float = 30.0) -> bool:
    """Есть ли включённая вторичная нода с is_healthy=False (кэш ~30 с)."""
    global _cached, _checked_at
    now = time.monotonic()
    if now - _checked_at <= max_age_sec:
        return _cached

    secondaries = await nodes_db.get_secondary_nodes()
    _cached = bool(secondaries) and any(
        not n.get("is_healthy", True) for n in secondaries
    )
    _checked_at = now
    return _cached


async def get_secondary_node_notice() -> str | None:
    if await has_unhealthy_secondary_node():
        return SECONDARY_NODE_NOTICE
    return None


def invalidate_secondary_node_notice_cache() -> None:
    global _checked_at
    _checked_at = 0.0
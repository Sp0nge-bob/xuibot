"""Идемпотентность и rate-limit для Platega webhook."""
from __future__ import annotations

import time
from collections import deque

from config.settings import settings
from db.webhook_dedup import finalize_webhook, try_acquire_webhook

_rate_hits: dict[str, deque[float]] = {}


async def acquire_webhook(tx_id: str, status: str) -> bool:
    """
    False — дубликат (уже успешно обработан в пределах TTL).
    True — можно обрабатывать.
    """
    return await try_acquire_webhook(tx_id, status)


async def complete_webhook(tx_id: str, status: str, *, success: bool) -> None:
    await finalize_webhook(tx_id, status, success=success)


def webhook_rate_limited(client_ip: str) -> bool:
    limit = int(settings.WEBHOOK_RATE_LIMIT_PER_MIN)
    if limit <= 0:
        return False
    ip = (client_ip or "unknown").strip() or "unknown"
    now = time.monotonic()
    bucket = _rate_hits.setdefault(ip, deque())
    while bucket and now - bucket[0] > 60.0:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False
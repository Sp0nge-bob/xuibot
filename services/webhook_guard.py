"""Идемпотентность и rate-limit для Platega webhook."""
from __future__ import annotations

import time
from collections import deque

from config.settings import settings

_processed: dict[str, float] = {}
_rate_hits: dict[str, deque[float]] = {}


def _cleanup_processed(now: float, ttl: float) -> None:
    stale = [k for k, ts in _processed.items() if now - ts > ttl]
    for key in stale:
        _processed.pop(key, None)


def is_duplicate_webhook(tx_id: str, status: str) -> bool:
    ttl = float(settings.WEBHOOK_IDEMPOTENCY_TTL_SEC)
    key = f"{tx_id}:{(status or '').upper()}"
    now = time.monotonic()
    _cleanup_processed(now, ttl)
    if key in _processed and now - _processed[key] < ttl:
        return True
    _processed[key] = now
    return False


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
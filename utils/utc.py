"""UTC-время для сроков подписки.

В проекте naive datetime в БД означают UTC (исторически через datetime.utcnow).
Нельзя вызывать .timestamp() у naive datetime: Python считает его локальным —
на серверах не в UTC это сдвигает expiry на панели и после sync отъедает день.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_UTC = timezone.utc
_MS_PER_DAY = 24 * 60 * 60 * 1000


def utc_now() -> datetime:
    """Naive UTC «сейчас» (для записи в SQLite / сравнений как раньше)."""
    return datetime.now(_UTC).replace(tzinfo=None)


def utc_now_ms() -> int:
    return int(datetime.now(_UTC).timestamp() * 1000)


def parse_utc(iso: str | datetime) -> datetime:
    """Разобрать ISO из БД. Naive → UTC; aware → в UTC naive."""
    if isinstance(iso, datetime):
        dt = iso
    else:
        s = str(iso or "").strip()
        if not s:
            raise ValueError("empty datetime")
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        return dt.astimezone(_UTC).replace(tzinfo=None)
    return dt


def utc_iso_to_ms(iso: str | datetime) -> int:
    """ISO/naive-UTC → unix ms (всегда как UTC, не как локаль сервера)."""
    dt = parse_utc(iso)
    return int(dt.replace(tzinfo=_UTC).timestamp() * 1000)


def ms_to_utc_iso(ms: int) -> str:
    """Unix ms → naive UTC ISO."""
    if not ms:
        return utc_now().isoformat()
    return datetime.fromtimestamp(ms / 1000.0, tz=_UTC).replace(tzinfo=None).isoformat()


def add_days_utc(dt: datetime | str, days: int) -> datetime:
    return parse_utc(dt) + timedelta(days=int(days))


def days_from_now_ms(days: int, *, from_ms: int | None = None) -> int:
    base = utc_now_ms() if from_ms is None else int(from_ms)
    return base + int(days) * _MS_PER_DAY

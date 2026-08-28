"""Регрессия: naive end_date из БД → ms как UTC, не как локаль сервера."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.utc import ms_to_utc_iso, parse_utc, utc_iso_to_ms


def test_naive_midnight_is_utc_not_local() -> None:
    iso = "2026-04-26T00:00:00"
    ms = utc_iso_to_ms(iso)
    expected = int(datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert ms == expected, f"{ms} != {expected}"
    # Старый баг: .timestamp() на naive давал другой день на TZ≠UTC
    buggy = int(datetime.fromisoformat(iso).timestamp() * 1000)
    # На UTC-сервере совпадёт; на остальных buggy меньше expected
    if buggy != expected:
        assert ms_to_utc_iso(ms).startswith("2026-04-26")
        assert not ms_to_utc_iso(buggy).startswith("2026-04-26") or buggy == expected


def test_extend_preserves_calendar_day() -> None:
    from datetime import timedelta

    start = parse_utc("2026-04-26")
    end = start + timedelta(days=30)
    assert end.date().isoformat() == "2026-05-26"
    assert ms_to_utc_iso(utc_iso_to_ms(end.isoformat())).startswith("2026-05-26")


if __name__ == "__main__":
    test_naive_midnight_is_utc_not_local()
    test_extend_preserves_calendar_day()
    print("ok: utc expiry helpers")

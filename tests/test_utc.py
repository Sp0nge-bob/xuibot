"""Регрессия UTC: naive datetime в БД = UTC, не локаль сервера."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from utils.utc import add_days_utc, days_from_now_ms, ms_to_utc_iso, parse_utc, utc_iso_to_ms

_MS_PER_DAY = 24 * 60 * 60 * 1000


def test_parse_utc_naive_iso_unchanged():
    dt = parse_utc("2026-04-26T00:00:00")
    assert dt == datetime(2026, 4, 26, 0, 0, 0)
    assert dt.tzinfo is None


def test_parse_utc_aware_to_utc_naive():
    dt = parse_utc("2026-04-26T00:00:00+03:00")
    assert dt == datetime(2026, 4, 25, 21, 0, 0)
    assert dt.tzinfo is None


def test_parse_utc_z_suffix():
    dt = parse_utc("2026-04-26T00:00:00Z")
    assert dt == datetime(2026, 4, 26, 0, 0, 0)


def test_parse_utc_datetime_input():
    src = datetime(2026, 4, 26, 12, 0, 0)
    assert parse_utc(src) == src
    aware = datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc)
    assert parse_utc(aware) == datetime(2026, 4, 26, 0, 0, 0)


def test_parse_utc_empty_raises():
    with pytest.raises(ValueError, match="empty datetime"):
        parse_utc("")


def test_utc_iso_to_ms_is_utc_not_host_tz():
    # Не хардкодить unix-ms года: 1735689600000 — это 2025-01-01, не 2026.
    iso = "2026-01-01T00:00:00"
    expected = int(datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert utc_iso_to_ms(iso) == expected
    # Известный прод-баг: 26.04 + naive .timestamp() съедал день на TZ≠UTC.
    april = "2026-04-26T00:00:00"
    april_ms = utc_iso_to_ms(april)
    april_expected = int(datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    assert april_ms == april_expected


def test_ms_to_utc_iso_zero_does_not_raise():
    out = ms_to_utc_iso(0)
    assert "T" in out
    ms = utc_iso_to_ms("2026-04-26T00:00:00")
    assert ms_to_utc_iso(ms).startswith("2026-04-26T00:00:00")


def test_add_days_utc_month_boundary():
    dt = add_days_utc("2026-01-31", 1)
    assert dt.date().isoformat() == "2026-02-01"


def test_days_from_now_ms_from_zero():
    assert days_from_now_ms(30, from_ms=0) == 30 * _MS_PER_DAY

"""Анти-флуд webhook по IP, окно 60 с."""
from __future__ import annotations

from services import webhook_guard


def test_rate_limit_zero_always_false(monkeypatch):
    monkeypatch.setattr(webhook_guard.settings, "WEBHOOK_RATE_LIMIT_PER_MIN", 0)
    webhook_guard._rate_hits.clear()
    assert webhook_guard.webhook_rate_limited("1.1.1.1") is False
    assert webhook_guard.webhook_rate_limited("1.1.1.1") is False


def test_rate_limit_two_hits_then_block(monkeypatch):
    monkeypatch.setattr(webhook_guard.settings, "WEBHOOK_RATE_LIMIT_PER_MIN", 2)
    webhook_guard._rate_hits.clear()
    assert webhook_guard.webhook_rate_limited("10.0.0.1") is False
    assert webhook_guard.webhook_rate_limited("10.0.0.1") is False
    assert webhook_guard.webhook_rate_limited("10.0.0.1") is True


def test_rate_limit_separate_ips(monkeypatch):
    monkeypatch.setattr(webhook_guard.settings, "WEBHOOK_RATE_LIMIT_PER_MIN", 1)
    webhook_guard._rate_hits.clear()
    assert webhook_guard.webhook_rate_limited("10.0.0.1") is False
    assert webhook_guard.webhook_rate_limited("10.0.0.2") is False
    assert webhook_guard.webhook_rate_limited("10.0.0.1") is True


def test_rate_limit_window_expires(monkeypatch):
    monkeypatch.setattr(webhook_guard.settings, "WEBHOOK_RATE_LIMIT_PER_MIN", 1)
    webhook_guard._rate_hits.clear()
    times = iter([0.0, 1.0, 61.0])
    monkeypatch.setattr(webhook_guard.time, "monotonic", lambda: next(times))
    assert webhook_guard.webhook_rate_limited("10.0.0.9") is False
    assert webhook_guard.webhook_rate_limited("10.0.0.9") is True
    assert webhook_guard.webhook_rate_limited("10.0.0.9") is False

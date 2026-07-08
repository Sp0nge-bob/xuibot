"""Unit-тесты форматирования и рекомендаций диагностики (без live HTTP/bot)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.admin_diagnostics import (
    build_recommendations,
    format_diagnostics_section,
    format_diagnostics_summary,
)
from services.panel_server_status import (
    format_server_status_short,
    normalize_server_status_obj,
)


def _base_report(**overrides) -> dict:
    report = {
        "checked_at": "2026-07-01 12:00:00 UTC",
        "elapsed_ms": 500,
        "overall_ok": True,
        "issues": [],
        "warnings": [],
        "telegram": {"ok": True, "latency_ms": 40, "detail": "@testbot"},
        "polling_lock": {"held": True, "alive": True, "own_process": True, "pid": 1234},
        "primary_ready": True,
        "primary_error": "",
        "primary_name": "Primary",
        "primary_inbounds": "1,2",
        "scheduler_running": True,
        "scheduler_jobs": 2,
        "scheduler_jobs_detail": [
            {"id": "heartbeat", "next_run": "07-01 12:05 UTC"},
        ],
        "fulfillment": {
            "workers_running": True,
            "workers_alive": 2,
            "workers_configured": 2,
            "queue_depth": 0,
            "queue_max_size": 100,
        },
        "fulfillment_local": {},
        "webhook_process": {"pid": 5678, "port": 8080, "rate_limit_per_min": 60},
        "webhook_reachable": True,
        "probes": {
            "local_webhook": {"ok": True, "latency_ms": 5, "detail": "ok", "reachable": True},
            "platega": {"ok": True, "latency_ms": 100, "detail": "HTTP 200"},
            "public_webhook": {"ok": True, "latency_ms": 50, "detail": "ok"},
        },
        "public_webhook_configured": True,
        "nodes_summary": {"total": 2, "healthy": 2, "enabled": 2},
        "nodes": [
            {
                "id": 1,
                "name": "Primary",
                "is_primary": True,
                "is_enabled": True,
                "ok": True,
                "latency_ms": 30,
                "error": None,
                "uptime_24h": 0.99,
                "checked_live": True,
                "server_status": normalize_server_status_obj({
                    "cpu": 12.5,
                    "mem": {"current": 2147483648, "total": 8589934592},
                    "swap": {"current": 0, "total": 4294967296},
                    "disk": {"current": 53687091200, "total": 268435456000},
                }),
                "server_status_ok": True,
                "server_status_error": None,
                "server_status_checked": True,
            },
        ],
        "fsm": {
            "backend": "redis",
            "ok": True,
            "latency_ms": 2,
            "detail": "PONG",
            "state_ttl": 86400,
            "data_ttl": 86400,
        },
        "db_file": {"path": "data/bot.db", "exists": True, "size_mb": 4.2},
        "process_load_html": "💻 <b>Нагрузка</b>\nrun_bot.py",
        "secondary_degraded": False,
        "sync_disabled": False,
        "config": {
            "test_mode": False,
            "test_mode_overridden": False,
            "start_bot_in_webapp": False,
            "webhook_port": 8080,
            "webhook_path": "/platega-webhook",
            "public_webhook_url": "https://example.com/platega-webhook",
            "redis_url_set": True,
            "pid": 1234,
        },
        "recommendations": [],
    }
    report.update(overrides)
    return report


def test_summary_ok():
    text = format_diagnostics_summary(_base_report())
    assert "Диагностика системы" in text
    assert "Общий статус: OK" in text
    assert "Telegram" in text
    assert "bot.db" in text
    assert "Пользователей" not in text


def test_summary_redis_issue():
    report = _base_report(
        overall_ok=False,
        issues=["Redis/FSM"],
        fsm={"backend": "redis", "ok": False, "detail": "ConnectionError", "latency_ms": 10},
    )
    text = format_diagnostics_summary(report)
    assert "есть проблемы" in text
    assert "REDIS" in text


def test_recommendations_redis():
    report = _base_report(
        fsm={"backend": "redis", "ok": False, "detail": "down", "latency_ms": 1},
    )
    recs = build_recommendations(report)
    assert any("Redis" in r for r in recs)


def test_section_proc_has_scheduler():
    text = format_diagnostics_section(_base_report(), "proc")
    assert "Планировщик" in text
    assert "heartbeat" in text


def test_section_store_no_business_stats():
    text = format_diagnostics_section(_base_report(), "store")
    assert "SQLite" in text
    assert "платных" not in text.lower()


def test_summary_shows_node_resources():
    text = format_diagnostics_summary(_base_report())
    assert "Ресурсы нод" in text
    assert "CPU 12.5%" in text
    assert "RAM 2.0/8.0 GB" in text


def test_section_vpn_shows_server_status():
    text = format_diagnostics_section(_base_report(), "vpn")
    assert "server/status" in text
    assert "Swap 0.0/4.0 GB" in text


def test_format_server_status_short_from_apistatus_sample():
    status = normalize_server_status_obj({
        "cpu": 12.5,
        "mem": {"current": 2147483648, "total": 8589934592},
        "swap": {"current": 0, "total": 4294967296},
        "disk": {"current": 53687091200, "total": 268435456000},
    })
    short = format_server_status_short(status)
    assert "CPU 12.5%" in short
    assert "Disk 50.0/250.0 GB (20%)" in short


def main():
    test_summary_ok()
    test_summary_redis_issue()
    test_recommendations_redis()
    test_section_proc_has_scheduler()
    test_section_store_no_business_stats()
    test_summary_shows_node_resources()
    test_section_vpn_shows_server_status()
    test_format_server_status_short_from_apistatus_sample()
    print("admin diagnostics unit tests: OK")


if __name__ == "__main__":
    main()
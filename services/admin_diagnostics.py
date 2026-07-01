"""Сбор технической диагностики для админ-панели: процессы, webhook, ноды, хранилища."""
from __future__ import annotations

import asyncio
import html
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import httpx
from loguru import logger

from config.settings import settings
from db import bot_settings as bot_settings_db
from db import xui_nodes as nodes_db
from db.connection import DB_PATH
from services.fulfillment_queue import fulfillment_queue_status
from services.node_health import check_all_nodes_health
from services.primary_gate import (
    is_primary_ready,
    primary_unavailable_reason,
    refresh_primary_ready,
)
from services.process_stats import fetch_bot_load_block
from services.secondary_node_notice import has_unhealthy_secondary_node
from ui.theme import screen

DiagnosticsSection = Literal["proc", "web", "vpn", "store", "recs"]
DIAGNOSTICS_SECTIONS: tuple[tuple[str, DiagnosticsSection], ...] = (
    ("🤖 Процессы", "proc"),
    ("🌐 Webhook", "web"),
    ("🖧 VPN", "vpn"),
    ("💾 Хранилище", "store"),
)

_TELEGRAM_MAX = 4000


def _icon(ok: bool | None) -> str:
    if ok is True:
        return "🟢"
    if ok is False:
        return "🔴"
    return "🟡"


def _clip(text: str, max_len: int = 100) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _truncate_telegram(text: str, *, max_len: int = _TELEGRAM_MAX) -> str:
    if len(text) <= max_len:
        return text
    head_lines = text.split("\n")[:12]
    head = "\n".join(head_lines)
    suffix = "\n\n<i>… отчёт сокращён …</i>"
    budget = max_len - len(suffix)
    if len(head) > budget:
        head = head[: budget - 1] + "…"
    return head + suffix


def _db_file_info() -> dict[str, Any]:
    path = Path(DB_PATH)
    exists = path.is_file()
    size_mb = round(path.stat().st_size / (1024 * 1024), 2) if exists else 0.0
    return {"path": str(path), "exists": exists, "size_mb": size_mb}


async def _probe_fsm_storage() -> dict[str, Any]:
    url = (settings.REDIS_URL or "").strip()
    base = {
        "state_ttl": settings.FSM_STATE_TTL_SEC,
        "data_ttl": settings.FSM_DATA_TTL_SEC,
    }
    if not url:
        return {
            **base,
            "backend": "memory",
            "ok": True,
            "latency_ms": None,
            "detail": "MemoryStorage",
        }
    started = time.monotonic()
    try:
        import redis.asyncio as redis

        client = redis.from_url(url)
        await client.ping()
        latency_ms = int((time.monotonic() - started) * 1000)
        await client.aclose()
        return {
            **base,
            "backend": "redis",
            "ok": True,
            "latency_ms": latency_ms,
            "detail": "PONG",
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            **base,
            "backend": "redis",
            "ok": False,
            "latency_ms": latency_ms,
            "detail": _clip(f"{type(e).__name__}: {e}"),
        }


def _scheduler_jobs_detail(scheduler: Any) -> list[dict[str, Any]]:
    if not scheduler.running:
        return []
    jobs: list[dict[str, Any]] = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        if next_run is not None:
            next_s = next_run.astimezone(timezone.utc).strftime("%m-%d %H:%M UTC")
        else:
            next_s = "—"
        jobs.append({"id": job.id or "?", "next_run": next_s})
    return sorted(jobs, key=lambda row: row["id"])


def _polling_lock_view(lock: dict[str, Any]) -> tuple[bool | None, str]:
    if not lock.get("held"):
        return False, "lock не захвачен"
    if not lock.get("alive"):
        return False, f"PID {lock.get('pid')} не жив"
    if lock.get("own_process"):
        return True, f"PID {lock.get('pid')} (этот процесс)"
    return False, f"PID {lock.get('pid')} (другой процесс)"


async def _http_get_probe(
    url: str,
    *,
    timeout: float = 5.0,
    parse_health_json: bool = False,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
        latency_ms = int((time.monotonic() - started) * 1000)
        ok = resp.status_code < 500
        detail = f"HTTP {resp.status_code}"
        body: dict[str, Any] = {}
        if parse_health_json:
            try:
                body = resp.json()
            except Exception:
                body = {}
            status = body.get("status")
            if status == "ok":
                ok = True
                detail = "ok"
            elif status == "unavailable":
                ok = False
                detail = _clip(str(body.get("primary") or detail))
            elif resp.status_code == 503:
                ok = False
        return {
            "ok": ok,
            "latency_ms": latency_ms,
            "detail": detail,
            "url": url,
            "body": body,
            "reachable": True,
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "detail": _clip(f"{type(e).__name__}: {e}"),
            "url": url,
            "body": {},
            "reachable": False,
        }


def _public_health_url() -> str | None:
    pub = (settings.PUBLIC_WEBHOOK_URL or "").strip()
    if not pub:
        return None
    webhook_path = (settings.WEBHOOK_PATH or "/platega-webhook").rstrip("/")
    if pub.rstrip("/").endswith(webhook_path):
        base = pub.rstrip("/")[: -len(webhook_path)]
        return f"{base}/health"
    parsed = urlparse(pub)
    return urlunparse((parsed.scheme, parsed.netloc, "/health", "", "", ""))


def _fulfillment_view(report: dict[str, Any]) -> tuple[bool | None, str]:
    wh_reachable = report.get("webhook_reachable")
    ff = report.get("fulfillment") or {}
    ff_local = report.get("fulfillment_local") or {}
    if wh_reachable and ff:
        workers_run = ff.get("workers_running")
        alive = ff.get("workers_alive", 0)
        configured = ff.get("workers_configured", 0)
        depth = ff.get("queue_depth", 0)
        max_size = ff.get("queue_max_size", 0)
        shutting = ff.get("shutting_down")
        if workers_run and alive >= configured:
            ff_ok: bool | None = True
        elif workers_run:
            ff_ok = None
        else:
            ff_ok = False
        detail = f"воркеры {alive}/{configured}, очередь {depth}/{max_size}"
        if shutting:
            detail += " · останавливается"
        return ff_ok, detail
    if settings.START_BOT_IN_WEBAPP and ff_local.get("workers_running"):
        alive = ff_local.get("workers_alive", 0)
        configured = ff_local.get("workers_configured", 0)
        depth = ff_local.get("queue_depth", 0)
        max_size = ff_local.get("queue_max_size", 0)
        return True, f"воркеры {alive}/{configured}, очередь {depth}/{max_size} (этот процесс)"
    if settings.START_BOT_IN_WEBAPP:
        return False, "воркеры не запущены"
    if wh_reachable:
        return None, "нет данных fulfillment"
    return False, "нет связи с app.py"


async def collect_diagnostics(
    *,
    bot: Any = None,
    full_node_check: bool = True,
) -> dict[str, Any]:
    """Технический отчёт для экрана «Диагностика»."""
    started = time.monotonic()

    nodes_live: list[dict[str, Any]] = []
    if full_node_check:
        await refresh_primary_ready()
        try:
            nodes_live = await check_all_nodes_health()
        except Exception as e:
            logger.exception("Diagnostics node health failed: {}", e)
            nodes_live = []

    live_by_id = {int(r.get("node_id") or 0): r for r in nodes_live if r.get("node_id")}

    local_health_url = f"http://127.0.0.1:{settings.WEBHOOK_PORT}/health"
    public_health_url = _public_health_url()
    platega_url = settings.PLATEGA_BASE_URL.rstrip("/") + "/"

    probe_tasks: dict[str, Any] = {
        "local_webhook": _http_get_probe(local_health_url, parse_health_json=True),
        "platega": _http_get_probe(platega_url, timeout=8.0),
    }
    if public_health_url:
        probe_tasks["public_webhook"] = _http_get_probe(
            public_health_url,
            timeout=10.0,
            parse_health_json=True,
        )

    from bot.polling_lock import get_polling_lock_info
    from bot.scheduler import scheduler
    from services.test_mode import is_test_mode, is_test_mode_overridden

    probe_keys = list(probe_tasks.keys())
    gathered = await asyncio.gather(
        *probe_tasks.values(),
        is_test_mode(),
        is_test_mode_overridden(),
        nodes_db.nodes_summary(),
        nodes_db.list_nodes(),
        nodes_db.get_primary_node(),
        bot_settings_db.is_sync_disabled(),
        has_unhealthy_secondary_node(max_age_sec=0),
        _probe_fsm_storage(),
        fetch_bot_load_block(cpu_sample_sec=0.2),
        return_exceptions=True,
    )

    probe_results_list = gathered[: len(probe_keys)]
    extra = gathered[len(probe_keys) :]

    probes: dict[str, Any] = {}
    for key, result in zip(probe_keys, probe_results_list):
        if isinstance(result, Exception):
            probes[key] = {"ok": False, "latency_ms": None, "detail": _clip(str(result))}
        else:
            probes[key] = result

    def _unwrap(idx: int, default: Any) -> Any:
        val = extra[idx]
        return default if isinstance(val, Exception) else val

    test_mode = bool(_unwrap(0, False))
    test_mode_overridden = bool(_unwrap(1, False))
    summary = _unwrap(2, {}) or {}
    nodes_db_list = _unwrap(3, []) or []
    primary = _unwrap(4, None)
    sync_disabled = bool(_unwrap(5, False))
    secondary_degraded = bool(_unwrap(6, False))
    fsm_info = _unwrap(7, {"backend": "memory", "ok": True, "detail": "—"})
    process_load_html = _unwrap(8, "") or ""

    tg_info: dict[str, Any] = {"ok": None, "detail": "не проверялось"}
    if bot is not None:
        tg_started = time.monotonic()
        try:
            me = await bot.get_me()
            latency_ms = int((time.monotonic() - tg_started) * 1000)
            tg_info = {
                "ok": True,
                "latency_ms": latency_ms,
                "detail": f"@{me.username}" if me.username else str(me.id),
            }
        except Exception as e:
            latency_ms = int((time.monotonic() - tg_started) * 1000)
            tg_info = {
                "ok": False,
                "latency_ms": latency_ms,
                "detail": _clip(f"{type(e).__name__}: {e}"),
            }

    lock = get_polling_lock_info()
    nodes_report: list[dict[str, Any]] = []
    for node in nodes_db_list:
        nid = int(node.get("id") or 0)
        live = live_by_id.get(nid, {})
        ok = live.get("ok") if live else node.get("is_healthy")
        nodes_report.append({
            "id": nid,
            "name": node.get("name") or f"#{nid}",
            "is_primary": bool(node.get("is_primary")),
            "is_enabled": bool(node.get("is_enabled")),
            "ok": ok if node.get("is_enabled") else None,
            "latency_ms": live.get("latency_ms") or node.get("health_latency_ms"),
            "error": live.get("error") or node.get("last_health_error"),
            "uptime_24h": live.get("uptime_24h"),
            "checked_live": bool(live),
        })

    local_probe = probes.get("local_webhook") or {}
    local_body = local_probe.get("body") or {}
    fulfillment_remote = local_body.get("fulfillment") or {}
    webhook_remote = local_body.get("webhook") or {}

    issues, warnings = _build_issues_and_warnings(
        tg_info=tg_info,
        lock=lock,
        probes=probes,
        public_health_url=public_health_url,
        nodes_report=nodes_report,
        scheduler=scheduler,
        local_probe=local_probe,
        fulfillment_remote=fulfillment_remote,
        test_mode=test_mode,
        fsm_info=fsm_info if isinstance(fsm_info, dict) else {},
        secondary_degraded=secondary_degraded,
        sync_disabled=sync_disabled,
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    fulfillment_local = fulfillment_queue_status()

    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "elapsed_ms": elapsed_ms,
        "overall_ok": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "telegram": tg_info,
        "polling_lock": lock,
        "primary_ready": is_primary_ready(),
        "primary_error": primary_unavailable_reason(),
        "primary_name": (primary or {}).get("name"),
        "primary_inbounds": (primary or {}).get("inbound_ids") if primary else None,
        "scheduler_running": scheduler.running,
        "scheduler_jobs": len(scheduler.get_jobs()) if scheduler.running else 0,
        "scheduler_jobs_detail": _scheduler_jobs_detail(scheduler),
        "fulfillment": fulfillment_remote,
        "fulfillment_local": fulfillment_local,
        "webhook_process": webhook_remote,
        "webhook_reachable": bool(local_probe.get("reachable")),
        "probes": probes,
        "public_webhook_configured": bool(public_health_url),
        "nodes_summary": summary,
        "nodes": nodes_report,
        "fsm": fsm_info if isinstance(fsm_info, dict) else {},
        "db_file": _db_file_info(),
        "process_load_html": process_load_html,
        "secondary_degraded": secondary_degraded,
        "sync_disabled": sync_disabled,
        "config": {
            "test_mode": test_mode,
            "test_mode_overridden": test_mode_overridden,
            "start_bot_in_webapp": settings.START_BOT_IN_WEBAPP,
            "webhook_port": settings.WEBHOOK_PORT,
            "webhook_path": settings.WEBHOOK_PATH,
            "public_webhook_url": (settings.PUBLIC_WEBHOOK_URL or "").strip(),
            "redis_url_set": bool((settings.REDIS_URL or "").strip()),
            "pid": os.getpid(),
        },
    }
    report["recommendations"] = build_recommendations(report)
    return report


def _build_issues_and_warnings(
    *,
    tg_info: dict[str, Any],
    lock: dict[str, Any],
    probes: dict[str, Any],
    public_health_url: str | None,
    nodes_report: list[dict[str, Any]],
    scheduler: Any,
    local_probe: dict[str, Any],
    fulfillment_remote: dict[str, Any],
    test_mode: bool,
    fsm_info: dict[str, Any],
    secondary_degraded: bool,
    sync_disabled: bool,
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []

    platega_probe = probes.get("platega") or {}
    if platega_probe.get("ok") is False:
        issues.append("Platega API")
    if not tg_info.get("ok"):
        issues.append("Telegram API")
    if lock.get("held") and not lock.get("alive"):
        issues.append("polling lock (мертвый PID)")
    elif lock.get("held") and not lock.get("own_process"):
        issues.append("polling lock (другой процесс)")
    if not is_primary_ready():
        issues.append("★ Primary")
    pub_probe = probes.get("public_webhook")
    if public_health_url and pub_probe and pub_probe.get("ok") is False:
        issues.append("публичный webhook")
    for n in nodes_report:
        if n.get("is_enabled") and n.get("ok") is False:
            issues.append(f"нода {n.get('name')}")
    if secondary_degraded:
        issues.append("вторичные ноды")
    if not scheduler.running:
        issues.append("планировщик")
    if local_probe.get("reachable"):
        if not fulfillment_remote.get("workers_running"):
            issues.append("очередь выдачи (воркеры)")
        elif fulfillment_remote.get("workers_alive", 0) < fulfillment_remote.get(
            "workers_configured", 1
        ):
            issues.append("очередь выдачи (не все воркеры)")
    elif not settings.START_BOT_IN_WEBAPP:
        issues.append("webhook-процесс (app.py)")
    if not public_health_url and not test_mode:
        issues.append("PUBLIC_WEBHOOK_URL не задан")
    if test_mode and (settings.PUBLIC_WEBHOOK_URL or "").strip():
        issues.append("TEST_MODE + PUBLIC_WEBHOOK_URL")
    if fsm_info.get("backend") == "redis" and fsm_info.get("ok") is False:
        issues.append("Redis/FSM")

    if sync_disabled:
        warnings.append("синк нод выключен в админке")

    return issues, warnings


def build_recommendations(report: dict[str, Any]) -> list[str]:
    """Практические шаги по исправлению обнаруженных проблем."""
    recs: list[str] = []
    cfg = report.get("config") or {}
    port = cfg.get("webhook_port", settings.WEBHOOK_PORT)
    probes = report.get("probes") or {}

    tg = report.get("telegram") or {}
    if tg.get("ok") is False:
        recs.append(
            "Telegram API: проверьте BOT_TOKEN в .env, затем "
            "systemctl restart vpn-bot-telegram"
        )

    lock = report.get("polling_lock") or {}
    if lock.get("held") and not lock.get("alive"):
        recs.append(
            "Мёртвый polling lock: удалите data/.polling.lock и выполните "
            "systemctl restart vpn-bot-telegram"
        )
    elif lock.get("held") and not lock.get("own_process"):
        pid = lock.get("pid")
        recs.append(
            f"Запущено два бота (lock PID {pid}): systemctl stop vpn-bot-telegram; "
            "pkill -f run_bot.py; удалите data/.polling.lock; запустите снова"
        )
    elif not lock.get("held"):
        recs.append(
            "Polling lock не захвачен — перезапустите бота: "
            "systemctl restart vpn-bot-telegram"
        )

    fsm = report.get("fsm") or {}
    if fsm.get("backend") == "redis" and fsm.get("ok") is False:
        recs.append(
            "Redis недоступен: systemctl status redis-server · redis-cli ping · "
            "проверьте REDIS_URL в .env"
        )

    if not report.get("primary_ready"):
        err = (report.get("primary_error") or "").lower()
        if "не настроена" in err:
            recs.append(
                "★ Primary не настроена: Админка → Ноды → добавьте основную панель 3x-ui"
            )
        elif "отключена" in err:
            recs.append("★ Primary отключена: Админка → Ноды → включите основную ноду")
        else:
            recs.append(
                "★ Primary недоступна: Админка → Ноды → «Проверить»; "
                "проверьте URL (без /panel/ в конце), логин/пароль и доступность панели с VPS"
            )

    if report.get("secondary_degraded"):
        recs.append(
            "Вторичные ноды offline: Админка → Ноды → «Проверить»; "
            "пользователи увидят предупреждение о недоступном сервере"
        )

    if not report.get("webhook_reachable") and not cfg.get("start_bot_in_webapp"):
        recs.append(
            f"Webhook не запущен: systemctl start vpn-bot-web · "
            f"curl http://127.0.0.1:{port}/health · "
            "journalctl -u vpn-bot-web -n 50"
        )
        recs.append(
            "Или: sudo bash deploy/vpn-bot-ctl.sh → пункт 1 (установка/обновление)"
        )

    ff = report.get("fulfillment") or {}
    if report.get("webhook_reachable"):
        if not ff.get("workers_running"):
            recs.append(
                "Очередь выдачи не работает: systemctl restart vpn-bot-web "
                "(воркеры поднимаются при старте app.py)"
            )
        elif ff.get("workers_alive", 0) < ff.get("workers_configured", 1):
            recs.append(
                "Часть воркеров упала: journalctl -u vpn-bot-web -f, затем "
                "systemctl restart vpn-bot-web"
            )

    pub_probe = probes.get("public_webhook")
    pub_url = (cfg.get("public_webhook_url") or "").strip()
    if pub_url and pub_probe and pub_probe.get("ok") is False:
        recs.append(
            f"Публичный webhook: nginx/Caddy должен проксировать на 127.0.0.1:{port}; "
            "проверьте SSL, firewall (80/443)"
        )
        recs.append(f"Callback URL в ЛК Platega = {pub_url}")
        health_check = _public_health_url()
        if health_check:
            recs.append(f"Проверка снаружи: curl {health_check}")
    elif not pub_url and not cfg.get("test_mode"):
        recs.append(
            "Задайте PUBLIC_WEBHOOK_URL в .env (HTTPS + путь webhook) "
            "и тот же URL в ЛК Platega"
        )

    platega = probes.get("platega") or {}
    if platega.get("ok") is False:
        recs.append(
            "Platega недоступна: проверьте интернет на VPS и PLATEGA_BASE_URL в .env"
        )

    if not report.get("scheduler_running"):
        recs.append(
            "Планировщик остановлен: systemctl restart vpn-bot-telegram · "
            "tail -f data/logs/bot.log"
        )

    summary = report.get("nodes_summary") or {}
    if summary.get("total", 0) == 0:
        recs.append(
            "Нет нод в БД: Админка → Ноды → добавьте ★ Primary (URL, логин, инбаунды)"
        )

    bad_nodes = [
        n for n in (report.get("nodes") or [])
        if n.get("is_enabled") and n.get("ok") is False
    ]
    if bad_nodes:
        sample = ", ".join(str(n.get("name") or "?") for n in bad_nodes[:3])
        extra = f" (+{len(bad_nodes) - 3})" if len(bad_nodes) > 3 else ""
        recs.append(
            f"Ноды offline ({sample}{extra}): Админка → Ноды → «Проверить»; "
            "сверьте host, токен/пароль; с VPS: curl -k https://ваш-host/"
        )

    if cfg.get("test_mode") and pub_url:
        recs.append(
            "TEST_MODE=true при заданном PUBLIC_WEBHOOK_URL — отключите тест-режим для боевых оплат"
        )

    seen: set[str] = set()
    unique: list[str] = []
    for item in recs:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique[:12]


def _status_header(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if report.get("overall_ok"):
        lines.append("🟢 <b>Общий статус: OK</b>")
    else:
        issues = report.get("issues") or []
        lines.append("🔴 <b>Общий статус: есть проблемы</b>")
        if issues:
            shown = ", ".join(html.escape(i) for i in issues[:6])
            if len(issues) > 6:
                shown += f" +{len(issues) - 6}"
            lines.append(f"<i>{shown}</i>")
    warnings = report.get("warnings") or []
    if warnings:
        wshown = ", ".join(html.escape(w) for w in warnings[:3])
        lines.append(f"🟡 <i>{wshown}</i>")
    lines.append(
        f"⏱ <code>{html.escape(report.get('checked_at') or '—')}</code>"
        f" · {report.get('elapsed_ms', 0)} ms"
    )
    return lines


def format_diagnostics_summary(report: dict[str, Any]) -> str:
    """Компактная техническая сводка."""
    cfg = report.get("config") or {}
    tg = report.get("telegram") or {}
    lock_ok, _ = _polling_lock_view(report.get("polling_lock") or {})
    sched_ok = report.get("scheduler_running")
    jobs = report.get("scheduler_jobs", 0)
    primary_ok = report.get("primary_ready")
    summary = report.get("nodes_summary") or {}
    healthy = summary.get("healthy", 0)
    enabled = summary.get("enabled", 0)
    probes = report.get("probes") or {}
    local_ok = (probes.get("local_webhook") or {}).get("ok")
    platega_ok = (probes.get("platega") or {}).get("ok")
    ff_ok, ff_short = _fulfillment_view(report)
    fsm = report.get("fsm") or {}
    db_file = report.get("db_file") or {}
    sec = "⚠️" if report.get("secondary_degraded") else "🟢"

    blocks = [
        *_status_header(report),
        "",
        (
            f"{_icon(tg.get('ok'))} Telegram · "
            f"{_icon(lock_ok)} Polling · "
            f"{_icon(sched_ok)} Scheduler <b>{jobs}</b>"
        ),
        (
            f"{_icon(local_ok)} Webhook · "
            f"{_icon(platega_ok)} Platega · "
            f"{_icon(ff_ok)} Очередь <i>{html.escape(ff_short)}</i>"
        ),
        (
            f"{_icon(primary_ok)} ★ Primary · "
            f"Ноды <b>{healthy}</b>/<b>{enabled}</b> · "
            f"2nd {sec}"
        ),
        (
            f"{_icon(fsm.get('ok'))} "
            f"{html.escape(str(fsm.get('backend') or '—').upper())} · "
            f"bot.db <b>{db_file.get('size_mb', 0)}</b> MB"
        ),
        "",
        "<i>Нажмите раздел для подробностей</i>",
    ]
    return screen("🔍 <b>Диагностика системы</b>", "\n".join(blocks))


def format_diagnostics_section(report: dict[str, Any], section: DiagnosticsSection) -> str:
    if section == "recs":
        return _format_recommendations_section(report)
    if section == "proc":
        return _format_proc_section(report)
    if section == "web":
        return _format_web_section(report)
    if section == "vpn":
        return _format_vpn_section(report)
    if section == "store":
        return _format_store_section(report)
    return format_diagnostics_summary(report)


def _format_proc_section(report: dict[str, Any]) -> str:
    lines = ["<b>── Telegram ──</b>"]
    tg = report.get("telegram") or {}
    tg_lat = f" · {tg['latency_ms']} ms" if tg.get("latency_ms") is not None else ""
    lines.append(
        f"{_icon(tg.get('ok'))} API — "
        f"<code>{html.escape(str(tg.get('detail') or '—'))}</code>{tg_lat}"
    )

    lock_ok, lock_detail = _polling_lock_view(report.get("polling_lock") or {})
    lines += ["", "<b>── Polling ──</b>", f"{_icon(lock_ok)} {html.escape(lock_detail)}"]

    sched_ok = report.get("scheduler_running")
    jobs = report.get("scheduler_jobs", 0)
    sched_detail = f"работает · <b>{jobs}</b> задач" if sched_ok else "остановлен"
    lines += ["", "<b>── Планировщик ──</b>", f"{_icon(sched_ok)} {sched_detail}"]
    for job in report.get("scheduler_jobs_detail") or []:
        lines.append(
            f"• <code>{html.escape(str(job.get('id') or '—'))}</code> → "
            f"<code>{html.escape(str(job.get('next_run') or '—'))}</code>"
        )

    fsm = report.get("fsm") or {}
    backend = str(fsm.get("backend") or "—")
    fsm_lat = f" · {fsm['latency_ms']} ms" if fsm.get("latency_ms") is not None else ""
    lines += [
        "",
        "<b>── FSM storage ──</b>",
        (
            f"{_icon(fsm.get('ok'))} <b>{html.escape(backend.upper())}</b> — "
            f"<code>{html.escape(str(fsm.get('detail') or '—'))}</code>{fsm_lat}"
        ),
        (
            f"TTL state/data: <code>{fsm.get('state_ttl', '—')}</code> / "
            f"<code>{fsm.get('data_ttl', '—')}</code> с"
        ),
    ]

    cfg = report.get("config") or {}
    lines += ["", f"PID процесса: <code>{cfg.get('pid')}</code>"]

    load = (report.get("process_load_html") or "").strip()
    if load:
        lines += ["", load]

    body = "\n".join(lines)
    title = "🤖 <b>Процессы</b>"
    return _truncate_telegram(screen(title, body))


def _format_web_section(report: dict[str, Any]) -> str:
    lines: list[str] = []
    probes = report.get("probes") or {}
    cfg = report.get("config") or {}
    port = cfg.get("webhook_port", settings.WEBHOOK_PORT)
    local = probes.get("local_webhook") or {}
    local_lat = f" · {local['latency_ms']} ms" if local.get("latency_ms") is not None else ""
    local_addr = f"127.0.0.1:{port}/health"

    lines.append("<b>── Health endpoints ──</b>")
    if local.get("reachable") and (local.get("body") or {}).get("status") == "unavailable":
        lines.append(
            f"🟡 Локальный <code>{local_addr}</code> — app.py отвечает, "
            f"Primary: <code>{html.escape(str(local.get('detail') or '—'))}</code>{local_lat}"
        )
    else:
        lines.append(
            f"{_icon(local.get('ok'))} Локальный <code>{local_addr}</code> — "
            f"<code>{html.escape(str(local.get('detail') or '—'))}</code>{local_lat}"
        )

    if report.get("public_webhook_configured"):
        pub = probes.get("public_webhook") or {}
        pub_lat = f" · {pub['latency_ms']} ms" if pub.get("latency_ms") is not None else ""
        lines.append(
            f"{_icon(pub.get('ok'))} Публичный /health — "
            f"<code>{html.escape(str(pub.get('detail') or '—'))}</code>{pub_lat}"
        )
    else:
        lines.append("🟡 Публичный URL — <i>не задан (PUBLIC_WEBHOOK_URL)</i>")

    platega = probes.get("platega") or {}
    pl_lat = f" · {platega['latency_ms']} ms" if platega.get("latency_ms") is not None else ""
    lines.append(
        f"{_icon(platega.get('ok'))} Platega API — "
        f"<code>{html.escape(str(platega.get('detail') or '—'))}</code>{pl_lat}"
    )

    wh_proc = report.get("webhook_process") or {}
    wh_reachable = report.get("webhook_reachable")
    lines += ["", "<b>── Webhook-процесс ──</b>"]
    wh_pid = wh_proc.get("pid")
    if wh_reachable and wh_pid:
        mono = " · монолит" if wh_proc.get("start_bot_in_webapp") else ""
        lines.append(
            f"{_icon(True)} PID <code>{wh_pid}</code>, порт "
            f"<code>{wh_proc.get('port', port)}</code>{mono}"
        )
    elif wh_reachable:
        lines.append(f"{_icon(True)} отвечает на /health")
    else:
        lines.append(
            f"{_icon(False)} <code>127.0.0.1:{port}</code> недоступен "
            f"(<code>python app.py</code> не запущен?)"
        )

    ff_ok, ff_detail = _fulfillment_view(report)
    lines += ["", "<b>── Очередь выдачи ──</b>", f"{_icon(ff_ok)} {html.escape(ff_detail)}"]
    if wh_proc.get("rate_limit_per_min") is not None:
        lines.append(f"Rate-limit: <code>{wh_proc['rate_limit_per_min']}</code>/мин")

    test = "да" if cfg.get("test_mode") else "нет"
    test_src = "БД" if cfg.get("test_mode_overridden") else ".env"
    wh_path = cfg.get("webhook_path") or settings.WEBHOOK_PATH
    lines += [
        "",
        "<b>── Конфиг webhook ──</b>",
        f"TEST_MODE: <code>{test}</code> ({test_src})",
        f"Webhook path: <code>{html.escape(wh_path)}</code>",
        f"START_BOT_IN_WEBAPP: <code>{'да' if cfg.get('start_bot_in_webapp') else 'нет'}</code>",
    ]
    pub_url = (cfg.get("public_webhook_url") or "").strip()
    if pub_url:
        lines.append(f"PUBLIC_WEBHOOK_URL: <code>{html.escape(_clip(pub_url, 60))}</code>")

    return _truncate_telegram(screen("🌐 <b>Webhook</b>", "\n".join(lines)))


def _format_nodes_lines(nodes: list[dict[str, Any]], *, limit: int | None = None) -> list[str]:
    lines: list[str] = []
    shown = nodes if limit is None else nodes[:limit]
    for n in shown:
        if not n.get("is_enabled"):
            lines.append(f"⚪ {html.escape(n.get('name') or '—')} — выключена")
            continue
        star = " ★" if n.get("is_primary") else ""
        lat = n.get("latency_ms")
        lat_s = f" · {lat} ms" if lat is not None else ""
        uptime = n.get("uptime_24h")
        up_s = f" · uptime {int(uptime * 100)}%" if uptime is not None else ""
        err = n.get("error")
        err_s = (
            f" — <code>{html.escape(_clip(str(err), 60))}</code>"
            if err and not n.get("ok")
            else ""
        )
        status = "online" if n.get("ok") else "offline"
        live = " · live" if n.get("checked_live") else ""
        lines.append(
            f"{_icon(n.get('ok'))}{star} {html.escape(n.get('name') or '—')} — "
            f"<b>{status}</b>{lat_s}{up_s}{live}{err_s}"
        )
    if limit is not None and len(nodes) > limit:
        lines.append(f"<i>… ещё {len(nodes) - limit} нод</i>")
    return lines


def _format_vpn_section(report: dict[str, Any]) -> str:
    primary_ok = report.get("primary_ready")
    primary_err = report.get("primary_error") or ""
    primary_line = "готов" if primary_ok else _clip(primary_err, 100)
    primary_name = report.get("primary_name") or "—"
    inbounds = report.get("primary_inbounds")
    summary = report.get("nodes_summary") or {}
    nodes = report.get("nodes") or []

    lines = [
        "<b>── ★ Primary gate ──</b>",
        f"{_icon(primary_ok)} {html.escape(primary_line)}",
        f"Нода: <b>{html.escape(str(primary_name))}</b>",
        f"Inbounds: <code>{html.escape(str(inbounds or '—'))}</code>",
        "",
        "<b>── Синхронизация ──</b>",
    ]
    if report.get("sync_disabled"):
        lines.append("🟡 Автосинк нод — <b>выключен</b> в админке")
    else:
        lines.append("🟢 Автосинк нод — включён")

    if report.get("secondary_degraded"):
        lines.append("🔴 Вторичные ноды — <b>есть недоступные</b>")
    else:
        lines.append("🟢 Вторичные ноды — OK")

    lines += [
        "",
        "<b>── Ноды 3x-ui ──</b>",
        (
            f"Всего <b>{summary.get('total', 0)}</b> · "
            f"healthy <b>{summary.get('healthy', 0)}</b>/<b>{summary.get('enabled', 0)}</b>"
        ),
        *_format_nodes_lines(nodes, limit=None),
    ]
    return _truncate_telegram(screen("🖧 <b>VPN</b>", "\n".join(lines)))


def _format_store_section(report: dict[str, Any]) -> str:
    db_file = report.get("db_file") or {}
    fsm = report.get("fsm") or {}
    cfg = report.get("config") or {}
    fsm_lat = f" · {fsm['latency_ms']} ms" if fsm.get("latency_ms") is not None else ""

    exists = db_file.get("exists")
    db_ok = True if exists else False
    lines = [
        "<b>── SQLite ──</b>",
        f"{_icon(db_ok)} <code>{html.escape(str(db_file.get('path') or '—'))}</code>",
        f"Размер: <b>{db_file.get('size_mb', 0)}</b> MB",
        "",
        "<b>── FSM / Redis ──</b>",
        (
            f"{_icon(fsm.get('ok'))} <b>{html.escape(str(fsm.get('backend') or '—').upper())}</b> — "
            f"<code>{html.escape(str(fsm.get('detail') or '—'))}</code>{fsm_lat}"
        ),
    ]
    if cfg.get("redis_url_set"):
        lines.append("REDIS_URL: <code>задан</code>")
    else:
        lines.append("REDIS_URL: <code>не задан</code> (MemoryStorage)")

    lines += [
        "",
        "<b>── Runtime-конфиг ──</b>",
        f"PID: <code>{cfg.get('pid')}</code>",
        f"Webhook port: <code>{cfg.get('webhook_port', settings.WEBHOOK_PORT)}</code>",
        f"Webhook path: <code>{html.escape(str(cfg.get('webhook_path') or settings.WEBHOOK_PATH))}</code>",
        (
            f"START_BOT_IN_WEBAPP: "
            f"<code>{'да' if cfg.get('start_bot_in_webapp') else 'нет'}</code>"
        ),
        f"Группа 3x-ui: <code>{html.escape(settings.XUI_CLIENT_GROUP)}</code>",
    ]
    return _truncate_telegram(screen("💾 <b>Хранилище</b>", "\n".join(lines)))


def _format_recommendations_section(report: dict[str, Any]) -> str:
    recs = report.get("recommendations") or build_recommendations(report)
    if not recs:
        return screen(
            "📋 <b>Рекомендации</b>",
            "🟢 Проблем не обнаружено — рекомендации не требуются.",
        )
    lines = [f"<b>Найдено шагов: {len(recs)}</b>", ""]
    for idx, rec in enumerate(recs, start=1):
        lines.append(f"{idx}. {html.escape(rec)}")
    return _truncate_telegram(screen("📋 <b>Рекомендации</b>", "\n".join(lines)))


def format_diagnostics_text(report: dict[str, Any]) -> str:
    """Обратная совместимость: компактная сводка."""
    return format_diagnostics_summary(report)
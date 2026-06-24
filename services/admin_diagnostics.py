"""Сбор диагностики для админ-панели: ноды, webhook, бот, БД."""
from __future__ import annotations

import asyncio
import html
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from services.fulfillment_queue import fulfillment_queue_status
from services.node_health import check_all_nodes_health
from services.primary_gate import (
    is_primary_ready,
    primary_unavailable_reason,
    refresh_primary_ready,
)


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


async def collect_diagnostics(
    *,
    bot: Any = None,
    full_node_check: bool = True,
) -> dict[str, Any]:
    """Полный отчёт для экрана «Диагностика»."""
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

    probe_keys = list(probe_tasks.keys())
    probe_results_list = await asyncio.gather(*probe_tasks.values(), return_exceptions=True)
    probes: dict[str, Any] = {}
    for key, result in zip(probe_keys, probe_results_list):
        if isinstance(result, Exception):
            probes[key] = {"ok": False, "latency_ms": None, "detail": _clip(str(result))}
        else:
            probes[key] = result

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

    from bot.polling_lock import get_polling_lock_info
    from bot.scheduler import scheduler

    lock = get_polling_lock_info()
    stats = await db.get_admin_stats()
    summary = await nodes_db.nodes_summary()
    nodes_db_list = await nodes_db.list_nodes()

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

    elapsed_ms = int((time.monotonic() - started) * 1000)
    issues: list[str] = []

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
    if not scheduler.running:
        issues.append("планировщик")

    local_probe = probes.get("local_webhook") or {}
    local_body = local_probe.get("body") or {}
    fulfillment_remote = local_body.get("fulfillment") or {}
    webhook_remote = local_body.get("webhook") or {}

    if local_probe.get("reachable"):
        if not fulfillment_remote.get("workers_running"):
            issues.append("очередь выдачи (воркеры)")
        elif fulfillment_remote.get("workers_alive", 0) < fulfillment_remote.get(
            "workers_configured", 1
        ):
            issues.append("очередь выдачи (не все воркеры)")
    elif not settings.START_BOT_IN_WEBAPP:
        issues.append("webhook-процесс (app.py)")

    if not public_health_url and not settings.TEST_MODE:
        issues.append("PUBLIC_WEBHOOK_URL не задан")
    if settings.TEST_MODE and (settings.PUBLIC_WEBHOOK_URL or "").strip():
        issues.append("TEST_MODE + PUBLIC_WEBHOOK_URL")

    overall_ok = len(issues) == 0

    fulfillment_local = fulfillment_queue_status()

    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "elapsed_ms": elapsed_ms,
        "overall_ok": overall_ok,
        "issues": issues,
        "telegram": tg_info,
        "polling_lock": lock,
        "primary_ready": is_primary_ready(),
        "primary_error": primary_unavailable_reason(),
        "scheduler_running": scheduler.running,
        "scheduler_jobs": len(scheduler.get_jobs()) if scheduler.running else 0,
        "fulfillment": fulfillment_remote,
        "fulfillment_local": fulfillment_local,
        "webhook_process": webhook_remote,
        "webhook_reachable": bool(local_probe.get("reachable")),
        "probes": probes,
        "public_webhook_configured": bool(public_health_url),
        "stats": stats,
        "nodes_summary": summary,
        "nodes": nodes_report,
        "config": {
            "test_mode": settings.TEST_MODE,
            "start_bot_in_webapp": settings.START_BOT_IN_WEBAPP,
            "webhook_port": settings.WEBHOOK_PORT,
            "webhook_path": settings.WEBHOOK_PATH,
            "public_webhook_url": (settings.PUBLIC_WEBHOOK_URL or "").strip(),
            "pid": os.getpid(),
        },
    }
    report["recommendations"] = build_recommendations(report)
    return report


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
    return unique[:10]


def format_diagnostics_text(report: dict[str, Any]) -> str:
    """HTML-текст для Telegram (до ~4000 символов)."""
    lines: list[str] = [
        "🔍 <b>Диагностика системы</b>",
        "━━━━━━━━━━━━━━━━",
        f"⏱ <code>{html.escape(report.get('checked_at') or '—')}</code>"
        f" · {report.get('elapsed_ms', 0)} ms",
        "",
    ]

    if report.get("overall_ok"):
        lines.append("🟢 <b>Общий статус: OK</b>")
    else:
        issues = report.get("issues") or []
        lines.append("🔴 <b>Общий статус: есть проблемы</b>")
        if issues:
            shown = ", ".join(html.escape(i) for i in issues[:8])
            if len(issues) > 8:
                shown += f" +{len(issues) - 8}"
            lines.append(f"<i>{shown}</i>")
    lines.append("")

    lines.append("<b>━━ Бот ━━</b>")
    tg = report.get("telegram") or {}
    tg_lat = f" · {tg['latency_ms']} ms" if tg.get("latency_ms") is not None else ""
    lines.append(
        f"{_icon(tg.get('ok'))} Telegram API — "
        f"<code>{html.escape(str(tg.get('detail') or '—'))}</code>{tg_lat}"
    )

    lock = report.get("polling_lock") or {}
    if not lock.get("held"):
        lock_ok: bool | None = False
        lock_detail = "lock не захвачен"
    elif not lock.get("alive"):
        lock_ok = False
        lock_detail = f"PID {lock.get('pid')} не жив"
    elif lock.get("own_process"):
        lock_ok = True
        lock_detail = f"PID {lock.get('pid')} (этот процесс)"
    else:
        lock_ok = False
        lock_detail = f"PID {lock.get('pid')} (другой процесс)"
    lines.append(f"{_icon(lock_ok)} Polling — {html.escape(lock_detail)}")

    sched_ok = report.get("scheduler_running")
    jobs = report.get("scheduler_jobs", 0)
    sched_detail = f"работает ({jobs} задач)" if sched_ok else "остановлен"
    lines.append(f"{_icon(sched_ok)} Планировщик — {sched_detail}")

    primary_ok = report.get("primary_ready")
    primary_err = report.get("primary_error") or ""
    primary_line = "готов" if primary_ok else _clip(primary_err, 80)
    lines.append(f"{_icon(primary_ok)} ★ Primary gate — {html.escape(primary_line)}")
    lines.append("")

    lines.append("<b>━━ Webhook Platega ━━</b>")
    probes = report.get("probes") or {}
    local = probes.get("local_webhook") or {}
    local_lat = f" · {local['latency_ms']} ms" if local.get("latency_ms") is not None else ""
    local_addr = (
        f"127.0.0.1:{report.get('config', {}).get('webhook_port', settings.WEBHOOK_PORT)}/health"
    )
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
    wh_pid = wh_proc.get("pid")
    if wh_reachable and wh_pid:
        mono = " · монолит" if wh_proc.get("start_bot_in_webapp") else ""
        lines.append(
            f"{_icon(True)} Webhook-процесс — PID <code>{wh_pid}</code>"
            f", порт <code>{wh_proc.get('port', settings.WEBHOOK_PORT)}</code>{mono}"
        )
    elif wh_reachable:
        lines.append(f"{_icon(True)} Webhook-процесс — отвечает на /health")
    else:
        lines.append(
            f"{_icon(False)} Webhook-процесс — "
            f"<code>127.0.0.1:{settings.WEBHOOK_PORT}</code> недоступен "
            f"(<code>python app.py</code> не запущен?)"
        )

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
            ff_ok = True
        elif workers_run:
            ff_ok = None
        else:
            ff_ok = False
        ff_detail = (
            f"воркеры <b>{alive}</b>/<b>{configured}</b>, "
            f"очередь <b>{depth}</b>/<b>{max_size}</b>"
        )
        if shutting:
            ff_detail += " · <i>останавливается</i>"
        lines.append(f"{_icon(ff_ok)} Очередь выдачи — {ff_detail}")
    elif settings.START_BOT_IN_WEBAPP and ff_local.get("workers_running"):
        depth = ff_local.get("queue_depth", 0)
        max_size = ff_local.get("queue_max_size", 0)
        alive = ff_local.get("workers_alive", 0)
        configured = ff_local.get("workers_configured", 0)
        lines.append(
            f"{_icon(True)} Очередь выдачи — воркеры <b>{alive}</b>/<b>{configured}</b>, "
            f"очередь <b>{depth}</b>/<b>{max_size}</b> (этот процесс)"
        )
    elif settings.START_BOT_IN_WEBAPP:
        lines.append(f"{_icon(False)} Очередь выдачи — воркеры не запущены")
    else:
        lines.append(f"{_icon(False)} Очередь выдачи — данные недоступны (нет связи с app.py)")

    if wh_proc.get("rate_limit_per_min") is not None:
        lines.append(
            f"Rate-limit webhook: <code>{wh_proc['rate_limit_per_min']}</code>/мин"
        )
    lines.append("")

    summary = report.get("nodes_summary") or {}
    nodes = report.get("nodes") or []
    lines.append("<b>━━ Ноды 3x-ui ━━</b>")
    lines.append(
        f"Всего <b>{summary.get('total', 0)}</b> · "
        f"healthy <b>{summary.get('healthy', 0)}</b>/<b>{summary.get('enabled', 0)}</b>"
    )
    for n in nodes[:12]:
        if not n.get("is_enabled"):
            lines.append(f"⚪ {html.escape(n.get('name') or '—')} — выключена")
            continue
        star = " ★" if n.get("is_primary") else ""
        lat = n.get("latency_ms")
        lat_s = f" · {lat} ms" if lat is not None else ""
        uptime = n.get("uptime_24h")
        up_s = f" · uptime {int(uptime * 100)}%" if uptime is not None else ""
        err = n.get("error")
        err_s = f" — <code>{html.escape(_clip(str(err), 60))}</code>" if err and not n.get("ok") else ""
        status = "online" if n.get("ok") else "offline"
        lines.append(
            f"{_icon(n.get('ok'))}{star} {html.escape(n.get('name') or '—')} — "
            f"<b>{status}</b>{lat_s}{up_s}{err_s}"
        )
    if len(nodes) > 12:
        lines.append(f"<i>… ещё {len(nodes) - 12} нод (см. раздел «Ноды»)</i>")
    lines.append("")

    stats = report.get("stats") or {}
    lines.append("<b>━━ База данных ━━</b>")
    lines.append(
        f"👥 Пользователей: <b>{stats.get('users', 0)}</b> · "
        f"платных <b>{stats.get('paid_subs', 0)}</b> · "
        f"пробных <b>{stats.get('trial_subs', 0)}</b>"
    )
    lines.append(
        f"💰 Оплаченных заказов: <b>{stats.get('paid_orders', 0)}</b> · "
        f"тикетов: <b>{stats.get('pending_tickets', 0)}</b>"
    )
    lines.append("")

    cfg = report.get("config") or {}
    lines.append("<b>━━ Конфиг ━━</b>")
    lines.append(f"PID: <code>{cfg.get('pid')}</code>")
    test = "да" if cfg.get("test_mode") else "нет"
    mono = "да" if cfg.get("start_bot_in_webapp") else "нет"
    lines.append(f"TEST_MODE: <code>{test}</code> · START_BOT_IN_WEBAPP: <code>{mono}</code>")
    wh_path = cfg.get("webhook_path") or settings.WEBHOOK_PATH
    lines.append(f"Webhook path: <code>{html.escape(wh_path)}</code>")

    if not report.get("overall_ok"):
        recs = report.get("recommendations") or build_recommendations(report)
        if recs:
            lines.append("")
            lines.append("<b>━━ Рекомендации ━━</b>")
            for idx, rec in enumerate(recs[:8], start=1):
                lines.append(f"{idx}. {html.escape(rec)}")

    text = "\n".join(lines)
    if len(text) > 4000:
        # Сохраняем рекомендации, урезаем середину отчёта
        head = lines[:20]
        tail_labels = ("<b>━━ Рекомендации ━━</b>", "<b>━━ Конфиг ━━</b>")
        tail = []
        for i, line in enumerate(lines):
            if any(line.startswith(lbl) for lbl in tail_labels):
                tail = lines[i:]
                break
        text = "\n".join(head + ["<i>… отчёт сокращён …</i>"] + tail)
        if len(text) > 4000:
            text = text[:3990] + "\n…"
    return text
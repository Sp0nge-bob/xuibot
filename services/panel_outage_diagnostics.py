"""
Автодиагностика при массовом/Primary падении панелей 3x-ui.

Запуск из health-job: DNS → TCP/TLS → HTTP base → API read → вердикт.
Отчёт в ЛС BOT_ADMINS (с кулдауном, без спама каждые 5 мин).
"""
from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from config.settings import settings
from db import xui_nodes as nodes_db
from services.xui import normalize_xui_host

# Состояние процесса (не пишем в БД — достаточно per-process)
_incident_open: bool = False
_last_report_at: float = 0.0
_task: asyncio.Task[Any] | None = None
_lock = asyncio.Lock()

_TG_CHUNK = 3900


@dataclass
class _HttpProbe:
    ok: bool
    status: Optional[int] = None
    elapsed_ms: Optional[int] = None
    content_type: str = ""
    body_kind: str = ""  # json | html | text | empty | error
    error: str = ""
    hint: str = ""


@dataclass
class _NodeReport:
    name: str
    host_display: str
    is_primary: bool
    health_error: str
    port: int = 443
    dns_ok: bool = False
    dns_ips: list[str] = field(default_factory=list)
    dns_error: str = ""
    tcp_ok: bool = False
    tcp_ms: Optional[int] = None
    tcp_error: str = ""
    http_base: Optional[_HttpProbe] = None
    api_inbounds: Optional[_HttpProbe] = None
    api_clients: Optional[_HttpProbe] = None
    verdict: str = ""


def _short_host(url: str, max_len: int = 56) -> str:
    u = (url or "").strip()
    if len(u) <= max_len:
        return u
    return u[: max_len - 1] + "…"


def _parse_base(host: str) -> tuple[str, str, int]:
    """(base_url, hostname, port)."""
    raw = normalize_xui_host(host or "")
    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = "https://" + raw
    parsed = urlparse(raw)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    return base, hostname, port


def _classify_body(content_type: str, text: str) -> str:
    ct = (content_type or "").lower()
    sample = (text or "")[:400].lower()
    if "json" in ct or (sample.startswith("{") or sample.startswith("[")):
        return "json"
    if "html" in ct or "<html" in sample or "<!doctype" in sample:
        return "html"
    if not sample.strip():
        return "empty"
    return "text"


def _cf_hint(status: Optional[int], body_kind: str, text: str) -> str:
    sample = (text or "")[:800].lower()
    if status in (403, 429, 503) or body_kind == "html":
        if any(
            x in sample
            for x in (
                "cloudflare",
                "cf-ray",
                "attention required",
                "just a moment",
                "challenge-platform",
                "bot fight",
                "access denied",
            )
        ):
            return "похож на Cloudflare / WAF / challenge"
        if status == 403:
            return "HTTP 403 — WAF / ban IP / Bot Fight"
        if status == 429:
            return "HTTP 429 — rate limit"
        if status in (502, 504):
            return "gateway — nginx/origin недоступен"
        if status == 503:
            return "HTTP 503 — origin/CF under attack?"
    if status in (502, 504):
        return "gateway error (nginx/origin)"
    return ""


async def _dns_lookup(hostname: str) -> tuple[bool, list[str], str]:
    if not hostname:
        return False, [], "empty hostname"
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None, type=socket.SOCK_STREAM),
            timeout=8.0,
        )
        ips: list[str] = []
        for info in infos:
            addr = info[4][0]
            if addr not in ips:
                ips.append(addr)
        return (bool(ips), ips[:6], "" if ips else "no addresses")
    except Exception as e:
        return False, [], f"{type(e).__name__}: {e}"[:120]


async def _tcp_connect(hostname: str, port: int) -> tuple[bool, Optional[int], str]:
    if not hostname:
        return False, None, "empty hostname"
    started = time.monotonic()
    try:
        conn = asyncio.open_connection(hostname, port)
        reader, writer = await asyncio.wait_for(conn, timeout=10.0)
        ms = int((time.monotonic() - started) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        del reader
        return True, ms, ""
    except Exception as e:
        ms = int((time.monotonic() - started) * 1000)
        return False, ms, f"{type(e).__name__}: {e}"[:120]


async def _http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: Optional[dict[str, str]] = None,
) -> _HttpProbe:
    started = time.monotonic()
    try:
        resp = await client.get(url, headers=headers or {"Accept": "application/json, text/html, */*"})
        ms = int((time.monotonic() - started) * 1000)
        text = ""
        try:
            text = resp.text[:1200]
        except Exception:
            text = ""
        ctype = resp.headers.get("content-type", "")
        kind = _classify_body(ctype, text)
        hint = _cf_hint(resp.status_code, kind, text)
        ok = 200 <= resp.status_code < 400 and kind != "html"
        # для base URL 200 HTML — «сайт отвечает», но не API
        if "/panel/api/" not in url and resp.status_code < 500:
            ok = True
        return _HttpProbe(
            ok=ok,
            status=resp.status_code,
            elapsed_ms=ms,
            content_type=ctype.split(";")[0].strip()[:60],
            body_kind=kind,
            hint=hint,
        )
    except Exception as e:
        ms = int((time.monotonic() - started) * 1000)
        return _HttpProbe(
            ok=False,
            elapsed_ms=ms,
            error=f"{type(e).__name__}: {e}"[:160],
            body_kind="error",
        )


def _auth_headers(node: dict[str, Any]) -> dict[str, str]:
    """Заголовки 3x-ui: token панели, если есть (без логина/пароля в URL)."""
    headers = {"Accept": "application/json"}
    token = (node.get("token") or "").strip()
    if token:
        # py3xui / 3x-ui часто принимают session через cookie или header
        headers["Cookie"] = f"3x-ui={token}"
    return headers


def _node_verdict(rep: _NodeReport) -> str:
    if not rep.dns_ok:
        return "DNS fail — проблема резолва с VPS бота (или hostname)"
    if not rep.tcp_ok:
        return "TCP fail — сеть/firewall/порт закрыт с VPS бота"
    api_fail = (
        (rep.api_inbounds and not rep.api_inbounds.ok)
        and (rep.api_clients and not rep.api_clients.ok)
    )
    hints = []
    for p in (rep.http_base, rep.api_inbounds, rep.api_clients):
        if p and p.hint:
            hints.append(p.hint)
    if api_fail:
        if any("Cloudflare" in h or "WAF" in h or "429" in h or "403" in h for h in hints):
            return "API закрыт edge (CF/WAF/rate limit) — IP VPS бота?"
        if any(
            (p and p.status in (502, 503, 504))
            for p in (rep.api_inbounds, rep.api_clients, rep.http_base)
        ):
            return "Gateway/origin (nginx или панель не отвечает JSON)"
        if any(p and p.body_kind == "html" for p in (rep.api_inbounds, rep.api_clients)):
            return "API отдаёт HTML вместо JSON (challenge/login page)"
        if any(p and p.error and "Timeout" in p.error for p in (rep.api_inbounds, rep.api_clients)):
            return "Timeout API — панель/прокси тормозит или режет"
        return "API read fail (inbounds+clients) — как в health-check"
    if rep.http_base and rep.http_base.ok:
        return "HTTP base OK, API под вопросом"
    return "частичный сбой"


def _global_verdict(reports: list[_NodeReport]) -> str:
    if not reports:
        return "нет данных"
    n = len(reports)
    dns_fail = sum(1 for r in reports if not r.dns_ok)
    tcp_fail = sum(1 for r in reports if r.dns_ok and not r.tcp_ok)
    api_fail = sum(
        1
        for r in reports
        if r.dns_ok
        and r.tcp_ok
        and r.api_inbounds
        and r.api_clients
        and not r.api_inbounds.ok
        and not r.api_clients.ok
    )
    cf_like = sum(
        1
        for r in reports
        if any(
            p and p.hint and ("Cloudflare" in p.hint or "WAF" in p.hint or "403" in p.hint)
            for p in (r.http_base, r.api_inbounds, r.api_clients)
        )
    )

    if dns_fail == n:
        return (
            "🔴 Все ноды: DNS fail с VPS бота — "
            "проверить resolv.conf / блокировку DNS / сеть VPS"
        )
    if tcp_fail == n or (tcp_fail + dns_fail) == n:
        return (
            "🔴 Все ноды: TCP/сеть fail с VPS — "
            "исходящий доступ VPS, firewall, маршрут"
        )
    if api_fail >= max(2, (n + 1) // 2) and cf_like >= 1:
        return (
            "🔴 Массовый API fail + признаки edge/WAF — "
            "смотреть Cloudflare Security Events по IP VPS бота"
        )
    if api_fail >= max(2, (n + 1) // 2):
        return (
            "🔴 Массовый API read fail при живом TCP — "
            "общий reverse-proxy/CF/origin или rate limit; "
            "VPN-трафик клиентов может быть жив"
        )
    if any(r.is_primary and not (r.api_inbounds and r.api_inbounds.ok) for r in reports):
        return "🟠 ★ Primary API недоступна — пользователи в lockdown"
    return "🟡 Частичный сбой — см. разбор по нодам"


async def diagnose_node(
    node: dict[str, Any],
    *,
    health_error: str = "",
    client: httpx.AsyncClient,
) -> _NodeReport:
    name = str(node.get("name") or f"#{node.get('id')}")
    base, hostname, port = _parse_base(str(node.get("host") or ""))
    rep = _NodeReport(
        name=name,
        host_display=_short_host(base or hostname),
        is_primary=bool(node.get("is_primary")),
        health_error=(health_error or "")[:200],
        port=port,
    )

    rep.dns_ok, rep.dns_ips, rep.dns_error = await _dns_lookup(hostname)
    if rep.dns_ok:
        rep.tcp_ok, rep.tcp_ms, rep.tcp_error = await _tcp_connect(hostname, port)
    else:
        rep.tcp_error = "skipped (DNS fail)"

    if base:
        rep.http_base = await _http_get(client, base + "/")
        headers = _auth_headers(node)
        rep.api_inbounds = await _http_get(
            client, f"{base}/panel/api/inbounds/list", headers=headers,
        )
        rep.api_clients = await _http_get(
            client, f"{base}/panel/api/clients/list", headers=headers,
        )

    rep.verdict = _node_verdict(rep)
    return rep


def _format_http(label: str, p: Optional[_HttpProbe]) -> str:
    if p is None:
        return f"  {label}: —"
    if p.error:
        return f"  {label}: ❌ {p.error}" + (f" ({p.elapsed_ms}ms)" if p.elapsed_ms else "")
    parts = [f"HTTP {p.status}", p.body_kind or "?", f"{p.elapsed_ms}ms"]
    if p.content_type:
        parts.append(p.content_type)
    mark = "✅" if p.ok else "❌"
    line = f"  {label}: {mark} " + " · ".join(parts)
    if p.hint:
        line += f"\n    → {p.hint}"
    return line


def format_diagnostic_report(
    reports: list[_NodeReport],
    *,
    health_summary: str,
    trigger: str,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    global_v = _global_verdict(reports)
    lines = [
        "🔍 <b>Автодиагностика панелей</b>",
        "━━━━━━━━━━━━━━━━",
        f"⏰ {now}",
        f"📌 Триггер: {trigger}",
        f"📊 Health: {health_summary}",
        "",
        f"<b>Вердикт:</b>\n{global_v}",
        "",
        "<b>По нодам:</b>",
    ]
    for r in reports:
        star = "★ " if r.is_primary else ""
        lines.append(f"\n<b>{star}{r.name}</b> · <code>{r.host_display}</code>")
        if r.health_error:
            lines.append(f"  health: <code>{r.health_error[:120]}</code>")
        if r.dns_ok:
            ips = ", ".join(r.dns_ips[:4]) or "?"
            lines.append(f"  DNS: ✅ {ips}")
        else:
            lines.append(f"  DNS: ❌ {r.dns_error or 'fail'}")
        if r.tcp_ok:
            lines.append(f"  TCP:{r.port} ✅ {r.tcp_ms}ms")
        else:
            lines.append(f"  TCP:{r.port} ❌ {r.tcp_error or 'fail'}")
        lines.append(_format_http("HTTPS /", r.http_base))
        lines.append(_format_http("API inbounds/list", r.api_inbounds))
        lines.append(_format_http("API clients/list", r.api_clients))
        lines.append(f"  ➜ <i>{r.verdict}</i>")

    lines.extend(
        [
            "",
            "<b>Что проверить:</b>",
            "• Cloudflare → Security Events (IP VPS бота)",
            "• Bot Fight / WAF / Rate limit на зоне",
            "• С VPS: curl к panel/api/inbounds/list",
            "• VPN-клиенты могут работать — это admin API",
            "",
            "<i>Отчёт один на инцидент (пока ноды снова не станут OK).</i>",
        ]
    )
    return "\n".join(lines)


def _chunk_html(text: str, limit: int = _TG_CHUNK) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return parts


async def _notify_admins_report(text: str) -> int:
    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Panel outage diag: BOT_ADMINS empty")
        return 0
    from bot.sender import send_message

    chunks = _chunk_html(text)
    sent_admins = 0
    for admin_id in admin_ids:
        ok_any = False
        for i, chunk in enumerate(chunks):
            prefix = f"<i>часть {i + 1}/{len(chunks)}</i>\n" if len(chunks) > 1 and i else ""
            try:
                await send_message(admin_id, prefix + chunk)
                ok_any = True
            except Exception as e:
                logger.error("Panel outage diag notify {} failed: {}", admin_id, e)
        if ok_any:
            sent_admins += 1
    return sent_admins


def _should_trigger(results: list[dict[str, Any]], primary_id: Optional[int]) -> tuple[bool, str]:
    if not results:
        return False, ""
    failed = [r for r in results if not r.get("ok")]
    if not failed:
        return False, ""

    primary_down = False
    if primary_id:
        for r in results:
            if int(r.get("node_id") or 0) == primary_id and not r.get("ok"):
                primary_down = True
                break

    n_fail = len(failed)
    n_all = len(results)
    list_err = any(
        "inbounds/list" in str(r.get("error") or "")
        or "clients/list" in str(r.get("error") or "")
        for r in failed
    )

    if primary_down:
        extra = f" + ещё {n_fail - 1} нод" if n_fail > 1 else ""
        reason = "API list" if list_err else "health fail"
        return True, f"★ Primary down ({reason}){extra} · {n_fail}/{n_all}"
    if n_fail >= 2:
        return True, f"массовый fail нод ({n_fail}/{n_all})"
    if n_fail == n_all and n_all >= 2:
        return True, f"все ноды down ({n_all})"
    # одна secondary — не гоняем тяжёлую диагностику
    return False, ""


async def run_panel_outage_diagnostics(
    results: list[dict[str, Any]],
    *,
    trigger: str,
) -> str:
    """Полный прогон; возвращает текст отчёта."""
    nodes = await nodes_db.list_nodes(enabled_only=True)
    by_id = {int(n["id"]): n for n in nodes if n.get("id")}
    health_by_id = {
        int(r.get("node_id") or 0): r for r in results if r.get("node_id")
    }

    ok_n = sum(1 for r in results if r.get("ok"))
    health_summary = f"{ok_n}/{len(results)} health OK"

    timeout = float(getattr(settings, "PANEL_OUTAGE_DIAG_TIMEOUT_SEC", 12.0) or 12.0)
    reports: list[_NodeReport] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        verify=True,
    ) as client:
        sem = asyncio.Semaphore(3)

        async def _one(node: dict[str, Any]) -> _NodeReport:
            async with sem:
                hid = int(node.get("id") or 0)
                err = str((health_by_id.get(hid) or {}).get("error") or "")
                return await diagnose_node(node, health_error=err, client=client)

        # сначала упавшие, потом остальные (для полной картины)
        ordered = sorted(
            nodes,
            key=lambda n: (
                0 if not (health_by_id.get(int(n.get("id") or 0)) or {}).get("ok", True) else 1,
                0 if n.get("is_primary") else 1,
                str(n.get("name") or ""),
            ),
        )
        reports = list(await asyncio.gather(*[_one(n) for n in ordered]))

    return format_diagnostic_report(
        reports,
        health_summary=health_summary,
        trigger=trigger,
    )


async def _run_and_notify(results: list[dict[str, Any]], trigger: str) -> None:
    global _last_report_at
    try:
        logger.warning("Panel outage diagnostics start: {}", trigger)
        text = await run_panel_outage_diagnostics(results, trigger=trigger)
        sent = await _notify_admins_report(text)
        _last_report_at = time.monotonic()
        logger.warning(
            "Panel outage diagnostics done: admins_notified={} trigger={}",
            sent,
            trigger,
        )
    except Exception as e:
        logger.exception("Panel outage diagnostics failed: {}", e)
        try:
            await _notify_admins_report(
                "🔍 <b>Автодиагностика панелей</b>\n\n"
                f"❌ Сбой самой диагностики: <code>{type(e).__name__}: {str(e)[:200]}</code>\n"
                f"Триггер: {trigger}"
            )
        except Exception:
            pass


def _all_health_ok(results: list[dict[str, Any]]) -> bool:
    return bool(results) and all(r.get("ok") for r in results)


async def maybe_schedule_panel_outage_diagnostics(
    results: list[dict[str, Any]],
) -> bool:
    """
    Вызвать после health-check. True если задача диагностики поставлена.
    Один отчёт на инцидент; сброс инцидента когда все ноды снова OK.
    """
    global _incident_open, _task

    if not getattr(settings, "PANEL_OUTAGE_DIAG_ENABLED", True):
        return False

    if _all_health_ok(results):
        if _incident_open:
            logger.info("Panel outage incident closed — all nodes healthy")
        _incident_open = False
        return False

    primary = await nodes_db.get_primary_node()
    primary_id = int(primary["id"]) if primary and primary.get("id") else None
    should, trigger = _should_trigger(results, primary_id)
    if not should:
        return False

    if _incident_open:
        logger.debug("Panel outage diagnostics skipped — incident already open")
        return False

    cooldown = float(getattr(settings, "PANEL_OUTAGE_DIAG_COOLDOWN_SEC", 900) or 900)
    if _last_report_at and (time.monotonic() - _last_report_at) < cooldown:
        # флапы up/down чаще cooldown — не спамим
        logger.info(
            "Panel outage diagnostics skipped — cooldown {:.0f}s",
            cooldown - (time.monotonic() - _last_report_at),
        )
        return False

    async with _lock:
        if _incident_open:
            return False
        if _task is not None and not _task.done():
            return False
        _incident_open = True
        _task = asyncio.create_task(
            _run_and_notify(list(results), trigger),
            name="panel_outage_diagnostics",
        )
        return True

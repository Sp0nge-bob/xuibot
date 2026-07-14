"""Проверка нод для экрана диагностики: health + server/status за один проход с таймаутом."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from config.settings import settings
from db import xui_nodes as nodes_db
from services.node_alerts import process_health_transitions
from services.panel_server_status import fetch_panel_server_status
from services.primary_gate import apply_primary_health_results
from services.xui import _probe_panel_read_api, get_api_for_node, invalidate_api_cache


async def _probe_node_once(
    node: dict[str, Any],
    *,
    limit_sec: float,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Подключение к панели и server/status с раздельными таймаутами."""
    started = time.monotonic()
    connect_cap = min(max(3.0, limit_sec * 0.55), max(3.0, limit_sec - 2.0))

    api = await asyncio.wait_for(
        get_api_for_node(node, force_new=False),
        timeout=connect_cap,
    )
    elapsed = time.monotonic() - started
    read_cap = max(1.5, limit_sec - elapsed)
    if not await asyncio.wait_for(_probe_panel_read_api(api), timeout=read_cap):
        raise RuntimeError("inbounds/list и clients/list недоступны")

    elapsed = time.monotonic() - started
    status_cap = max(1.0, limit_sec - elapsed)
    status = await asyncio.wait_for(fetch_panel_server_status(api), timeout=status_cap)
    return True, status, None


async def probe_node_diagnostics(
    node: dict[str, Any],
    *,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    """Один проход к панели: health + server/status. Не блокирует event loop бесконечно."""
    node_id = int(node.get("id") or 0)
    name = node.get("name") or f"#{node_id}"
    limit = float(
        timeout_sec if timeout_sec is not None else settings.DIAGNOSTICS_NODE_TIMEOUT_SEC
    )

    if not node.get("is_enabled"):
        return {
            "node_id": node_id,
            "name": name,
            "ok": None,
            "latency_ms": None,
            "error": None,
            "uptime_24h": None,
            "server_status": None,
            "server_status_ok": None,
            "server_status_error": None,
            "server_status_checked": False,
            "skipped": True,
        }

    started = time.monotonic()
    ok = False
    error: str | None = None
    status: dict[str, Any] | None = None

    try:
        ok, status, error = await asyncio.wait_for(
            _probe_node_once(node, limit_sec=limit),
            timeout=limit,
        )
    except asyncio.TimeoutError:
        error = f"timeout {limit:.0f}s"
        invalidate_api_cache(node_id)
        logger.warning("Diagnostics node {} ({}): {}", node_id, name, error)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"[:200]
        invalidate_api_cache(node_id)
        logger.debug("Diagnostics node {} ({}): {}", node_id, name, error)

    latency_ms = int((time.monotonic() - started) * 1000)

    if node_id:
        await nodes_db.record_health_check(
            node_id, ok=ok, latency_ms=latency_ms, error=error,
        )
        if not node.get("is_primary"):
            from services.secondary_node_notice import invalidate_secondary_node_notice_cache

            invalidate_secondary_node_notice_cache()

    uptime = await nodes_db.get_uptime_24h(node_id) if node_id else None
    return {
        "node_id": node_id,
        "name": name,
        "ok": ok,
        "latency_ms": latency_ms,
        "error": error,
        "uptime_24h": uptime,
        "server_status": status,
        "server_status_ok": True if status else (False if error else None),
        "server_status_error": error if not status else None,
        "server_status_checked": True,
        "skipped": False,
    }


async def probe_all_nodes_for_diagnostics(
    nodes: list[dict[str, Any]],
    *,
    timeout_sec: float | None = None,
) -> list[dict[str, Any]]:
    enabled = [n for n in nodes if n.get("is_enabled")]
    if not enabled:
        return []

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    per_node_timeout = float(
        timeout_sec if timeout_sec is not None else settings.DIAGNOSTICS_NODE_TIMEOUT_SEC
    )

    async def _one(node: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                return await probe_node_diagnostics(node, timeout_sec=per_node_timeout)
            except Exception as e:
                logger.error("Diagnostics probe error for node {}: {}", node.get("id"), e)
                return {
                    "node_id": node.get("id"),
                    "name": node.get("name"),
                    "ok": False,
                    "error": str(e)[:200],
                    "server_status_checked": False,
                    "skipped": False,
                }

    results = list(await asyncio.gather(*[_one(n) for n in enabled]))
    await process_health_transitions(results)
    await apply_primary_health_results(results)
    return results
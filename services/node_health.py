"""Проверка доступности панелей 3x-ui."""
import asyncio
import time
from typing import Any, Optional

from loguru import logger

from config.settings import settings
from db import xui_nodes as nodes_db
from services.xui import _probe_panel_read_api, get_api_for_node, invalidate_api_cache


async def _check_node_health_impl(node: dict[str, Any]) -> dict[str, Any]:
    node_id = node["id"]
    started = time.monotonic()
    ok = False
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    try:
        api = await get_api_for_node(node, force_new=False)
        if not await _probe_panel_read_api(api):
            raise RuntimeError("inbounds/list и clients/list недоступны")
        latency_ms = int((time.monotonic() - started) * 1000)
        ok = True
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        error = f"{type(e).__name__}: {e}"[:200]
        invalidate_api_cache(node_id)
        logger.debug("Health check failed for node {} ({}): {}", node_id, node.get("name"), error)

    if node_id:
        await nodes_db.record_health_check(node_id, ok=ok, latency_ms=latency_ms, error=error)
        if not node.get("is_primary"):
            from services.secondary_node_notice import invalidate_secondary_node_notice_cache

            invalidate_secondary_node_notice_cache()

    uptime = await nodes_db.get_uptime_24h(node_id) if node_id else None
    return {
        "node_id": node_id,
        "name": node.get("name"),
        "ok": ok,
        "latency_ms": latency_ms,
        "error": error,
        "uptime_24h": uptime,
    }


async def check_node_health(
    node: dict[str, Any],
    *,
    timeout_sec: float | None = None,
) -> dict[str, Any]:
    if timeout_sec is not None and timeout_sec > 0:
        try:
            return await asyncio.wait_for(
                _check_node_health_impl(node),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            node_id = node.get("id")
            error = f"timeout {timeout_sec:.0f}s"
            invalidate_api_cache(node_id)
            logger.warning(
                "Health check timeout for node {} ({})",
                node_id,
                node.get("name"),
            )
            if node_id:
                await nodes_db.record_health_check(
                    node_id, ok=False, latency_ms=None, error=error,
                )
            return {
                "node_id": node_id,
                "name": node.get("name"),
                "ok": False,
                "latency_ms": None,
                "error": error,
                "uptime_24h": None,
            }
    return await _check_node_health_impl(node)


async def check_all_nodes_health(
    *,
    skip_node_ids: set[int] | None = None,
    timeout_sec: float | None = None,
) -> list[dict[str, Any]]:
    nodes = await nodes_db.list_nodes(enabled_only=True)
    if skip_node_ids:
        nodes = [n for n in nodes if int(n.get("id") or 0) not in skip_node_ids]
    if not nodes:
        return []

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(node: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                return await check_node_health(node, timeout_sec=timeout_sec)
            except Exception as e:
                logger.error("Health check error for node {}: {}", node.get("id"), e)
                return {
                    "node_id": node.get("id"),
                    "name": node.get("name"),
                    "ok": False,
                    "error": str(e)[:200],
                }

    return list(await asyncio.gather(*[_one(n) for n in nodes]))
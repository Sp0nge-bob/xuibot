"""Проверка доступности панелей 3x-ui."""
import time
from typing import Any, Optional

from loguru import logger

from db import xui_nodes as nodes_db
from services.xui import get_api_for_node, invalidate_api_cache


async def check_node_health(node: dict[str, Any]) -> dict[str, Any]:
    node_id = node["id"]
    started = time.monotonic()
    ok = False
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    try:
        api = await get_api_for_node(node, force_new=False)
        await api.inbound.get_list()
        latency_ms = int((time.monotonic() - started) * 1000)
        ok = True
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        error = f"{type(e).__name__}: {e}"[:200]
        invalidate_api_cache(node_id)
        logger.warning("Health check failed for node {} ({}): {}", node_id, node.get("name"), error)

    if node_id:
        await nodes_db.record_health_check(node_id, ok=ok, latency_ms=latency_ms, error=error)

    uptime = await nodes_db.get_uptime_24h(node_id) if node_id else None
    return {
        "node_id": node_id,
        "name": node.get("name"),
        "ok": ok,
        "latency_ms": latency_ms,
        "error": error,
        "uptime_24h": uptime,
    }


async def check_all_nodes_health() -> list[dict[str, Any]]:
    nodes = await nodes_db.list_nodes(enabled_only=True)
    results: list[dict[str, Any]] = []
    for node in nodes:
        try:
            results.append(await check_node_health(node))
        except Exception as e:
            logger.error("Health check error for node {}: {}", node.get("id"), e)
    healthy = sum(1 for r in results if r.get("ok"))
    logger.info("Node health: {}/{} healthy", healthy, len(results))
    return results
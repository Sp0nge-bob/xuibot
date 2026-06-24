"""Стартовая инициализация всех 3x-ui нод до запуска polling."""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from config.settings import settings
from db import xui_nodes as nodes_db
from services.node_alerts import process_health_transitions
from services.node_health import check_all_nodes_health
from services.xui import (
    ensure_bot_group_on_node,
    get_api_for_node,
    log_inbound_port_conflicts,
)


async def _ensure_groups_on_healthy_nodes(
    results: list[dict[str, Any]],
) -> None:
    nodes = await nodes_db.list_nodes(enabled_only=True)
    by_id = {int(n["id"]): n for n in nodes}
    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(result: dict[str, Any]) -> None:
        if not result.get("ok"):
            return
        node_id = int(result.get("node_id") or 0)
        node = by_id.get(node_id)
        if not node:
            return
        async with sem:
            try:
                api = await get_api_for_node(node)
                await ensure_bot_group_on_node(api, node_id)
            except Exception as e:
                logger.warning(
                    "Node startup: группа на [{}]: {}",
                    node.get("name"),
                    e,
                )

    await asyncio.gather(*[_one(r) for r in results])


async def initialize_nodes_at_startup() -> dict[str, Any]:
    """
    До polling: проверить все ноды, группу бота и инбаунды на primary.
    Возвращает сводку health-check.
    """
    logger.info("Node startup: инициализация панелей…")

    try:
        await asyncio.wait_for(log_inbound_port_conflicts(), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("Node startup: таймаут проверки инбаундов primary")
    except Exception as e:
        logger.warning("Node startup: инбаунды primary: {}", e)

    results = await check_all_nodes_health()
    await process_health_transitions(results)
    await _ensure_groups_on_healthy_nodes(results)

    healthy = sum(1 for r in results if r.get("ok"))
    total = len(results)
    if total:
        names_ok = ", ".join(
            (r.get("name") or f"#{r.get('node_id')}") for r in results if r.get("ok")
        )
        logger.info(
            "Node startup: {}/{} нод готовы ({})",
            healthy,
            total,
            names_ok or "—",
        )
        for r in results:
            if r.get("ok"):
                continue
            logger.warning(
                "Node startup: [{}] недоступна — {}",
                r.get("name"),
                r.get("error") or "unknown",
            )
    else:
        logger.info("Node startup: нод в реестре нет")

    return {"total": total, "healthy": healthy, "results": results}
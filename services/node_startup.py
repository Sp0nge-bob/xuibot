"""Стартовая инициализация всех 3x-ui нод (блокирующая или фоновая)."""
from __future__ import annotations

import asyncio
import time
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


def _log_startup_summary(
    results: list[dict[str, Any]],
    *,
    label: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    healthy = sum(1 for r in results if r.get("ok"))
    total = len(results)
    if total:
        names_ok = ", ".join(
            (r.get("name") or f"#{r.get('node_id')}") for r in results if r.get("ok")
        )
        logger.info(
            "Node startup ({}): {}/{} нод готовы за {} ms ({})",
            label,
            healthy,
            total,
            elapsed_ms,
            names_ok or "—",
        )
        for r in results:
            if r.get("ok"):
                continue
            logger.warning(
                "Node startup ({}): [{}] недоступна — {}",
                label,
                r.get("name"),
                r.get("error") or "unknown",
            )
    else:
        logger.info("Node startup ({}): нод в реестре нет", label)

    return {"total": total, "healthy": healthy, "results": results, "elapsed_ms": elapsed_ms}


async def initialize_nodes_at_startup(
    *,
    primary_result: dict[str, Any] | None = None,
    background: bool = False,
) -> dict[str, Any]:
    """
    Проверить ноды, группу бота и инбаунды primary.
    primary_result — уже выполненный health ★ Primary (без повторного connect).
    """
    label = "background" if background else "blocking"
    started = time.monotonic()
    logger.info("Node startup ({}): инициализация панелей…", label)

    timeout = settings.STARTUP_NODE_TIMEOUT_SEC if background else None
    skip_ids: set[int] = set()
    results: list[dict[str, Any]] = []

    if primary_result:
        results.append(primary_result)
        pid = int(primary_result.get("node_id") or 0)
        if pid:
            skip_ids.add(pid)

    secondary = await check_all_nodes_health(
        skip_node_ids=skip_ids or None,
        timeout_sec=timeout,
    )
    results.extend(secondary)
    await process_health_transitions(results)

    try:
        await asyncio.wait_for(log_inbound_port_conflicts(), timeout=15)
    except asyncio.TimeoutError:
        logger.warning("Node startup ({}): таймаут проверки инбаундов primary", label)
    except Exception as e:
        logger.warning("Node startup ({}): инбаунды primary: {}", label, e)

    await _ensure_groups_on_healthy_nodes(results)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return _log_startup_summary(results, label=label, elapsed_ms=elapsed_ms)
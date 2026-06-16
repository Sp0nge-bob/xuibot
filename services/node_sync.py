"""Репликация клиентов на вторичные панели 3x-ui."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from config.settings import settings
from db import database as db
from db import xui_nodes as nodes_db
from services.xui import (
    ensure_bot_group_on_node,
    get_api_for_node,
    replicate_client_on_node,
    sub_desired_state_from_db,
)


async def sync_subscription_to_node(sub: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    node_id = node["id"]
    email = sub["client_email"]
    try:
        state = sub_desired_state_from_db(sub)
        api = await get_api_for_node(node)
        await ensure_bot_group_on_node(api)
        action = await replicate_client_on_node(
            api,
            node=node,
            email=email,
            sub_id=state["sub_id"],
            expiry_ms=state["expiry_ms"],
            total_gb=state["total_gb"],
            enable=state["enable"],
        )
        return {"node_id": node_id, "email": email, "ok": True, "action": action}
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
        await nodes_db.update_node(node_id, last_sync_error=err)
        logger.error("Sync failed sub #{} → node {}: {}", sub.get("id"), node_id, err)
        return {"node_id": node_id, "email": email, "ok": False, "error": err}


async def sync_subscription_to_secondaries(sub_id: int) -> list[dict[str, Any]]:
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or not sub.get("is_active"):
        return []
    nodes = await nodes_db.get_secondary_nodes(healthy_only=True)
    if not nodes:
        return []
    results = []
    for node in nodes:
        results.append(await sync_subscription_to_node(sub, node))
        if results[-1].get("ok"):
            await nodes_db.update_node(
                node["id"],
                last_sync_at=datetime.utcnow().isoformat(),
                last_sync_error=None,
            )
    return results


async def sync_all_secondary_nodes() -> dict[str, int]:
    subs = await db.get_all_active_subscriptions()
    nodes = await nodes_db.get_secondary_nodes(healthy_only=True)
    if not nodes:
        logger.info("No healthy secondary nodes — sync skipped")
        return {"subs": 0, "nodes": 0, "ok": 0, "failed": 0}

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    stats = {"subs": len(subs), "nodes": len(nodes), "ok": 0, "failed": 0}

    async def _one(sub: dict) -> None:
        for node in nodes:
            async with sem:
                r = await sync_subscription_to_node(sub, node)
                if r.get("ok"):
                    stats["ok"] += 1
                    await nodes_db.update_node(
                        node["id"],
                        last_sync_at=datetime.utcnow().isoformat(),
                        last_sync_error=None,
                    )
                else:
                    stats["failed"] += 1

    await asyncio.gather(*[_one(sub) for sub in subs])
    logger.info(
        "Secondary sync done: subs={} nodes={} ok={} failed={}",
        stats["subs"], stats["nodes"], stats["ok"], stats["failed"],
    )
    return stats


def schedule_secondary_sync(sub_id: int) -> None:
    """Fire-and-forget репликация после оплаты/пробного."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_subscription_to_secondaries(sub_id))
    except RuntimeError:
        pass
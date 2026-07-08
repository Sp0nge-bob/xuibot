"""Статус сервера 3x-ui: GET /panel/api/server/status (CPU, RAM, swap, disk)."""
from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from py3xui import AsyncApi
from py3xui.api.api_base import ApiFields

from config.settings import settings
from services.xui import _throttle, get_api_for_node


def _bytes_pair(obj: dict[str, Any] | None) -> tuple[int, int]:
    if not obj:
        return 0, 0
    return int(obj.get("current") or 0), int(obj.get("total") or 0)


def _fmt_bytes_pair(obj: dict[str, Any] | None, *, decimals: int = 1) -> str:
    current, total = _bytes_pair(obj)
    if total <= 0:
        return "—"
    unit = 1024 ** 3
    cur = current / unit
    tot = total / unit
    pct = int(round(current / total * 100))
    return f"{cur:.{decimals}f}/{tot:.{decimals}f} GB ({pct}%)"


def _fmt_cpu(cpu: Any) -> str:
    if cpu is None:
        return "—"
    try:
        value = float(cpu)
    except (TypeError, ValueError):
        return "—"
    if value < 0.05:
        return "менее 0.1%"
    if value < 10:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{text or '0'}%"
    return f"{value:.1f}%"


def normalize_server_status_obj(obj: dict[str, Any] | None) -> dict[str, Any]:
    """Нормализованный срез ответа panel/api/server/status."""
    raw = obj or {}
    mem = raw.get("mem") if isinstance(raw.get("mem"), dict) else {}
    swap = raw.get("swap") if isinstance(raw.get("swap"), dict) else {}
    disk = raw.get("disk") if isinstance(raw.get("disk"), dict) else {}
    xray = raw.get("xray") if isinstance(raw.get("xray"), dict) else {}
    return {
        "cpu": raw.get("cpu"),
        "mem": {"current": mem.get("current"), "total": mem.get("total")},
        "swap": {"current": swap.get("current"), "total": swap.get("total")},
        "disk": {"current": disk.get("current"), "total": disk.get("total")},
        "xray_state": xray.get("state"),
        "xray_version": xray.get("version"),
    }


async def fetch_panel_server_status(api: AsyncApi) -> dict[str, Any]:
    url = api.client._url("panel/api/server/status")
    await _throttle()
    resp = await api.client._get(url, {"Accept": "application/json"})
    data = resp.json()
    if not data.get(ApiFields.SUCCESS, True):
        raise RuntimeError(str(data.get(ApiFields.MSG) or "server/status failed"))
    obj = data.get(ApiFields.OBJ) or {}
    if not isinstance(obj, dict):
        raise RuntimeError("server/status: invalid obj")
    return normalize_server_status_obj(obj)


async def fetch_node_server_status(node: dict[str, Any]) -> dict[str, Any]:
    """Один запрос server/status для ноды. ok=False при ошибке."""
    node_id = int(node.get("id") or 0)
    name = node.get("name") or f"#{node_id}"
    if not node.get("is_enabled"):
        return {
            "node_id": node_id,
            "name": name,
            "ok": None,
            "status": None,
            "error": None,
            "skipped": True,
        }
    try:
        api = await get_api_for_node(node, force_new=False)
        status = await fetch_panel_server_status(api)
        return {
            "node_id": node_id,
            "name": name,
            "ok": True,
            "status": status,
            "error": None,
            "skipped": False,
        }
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
        logger.debug("server/status failed for node {} ({}): {}", node_id, name, err)
        return {
            "node_id": node_id,
            "name": name,
            "ok": False,
            "status": None,
            "error": err,
            "skipped": False,
        }


async def fetch_all_nodes_server_status(
    nodes: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    if not nodes:
        return {}

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)

    async def _one(node: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            return await fetch_node_server_status(node)

    results = await asyncio.gather(*[_one(n) for n in nodes])
    return {int(r["node_id"]): r for r in results if r.get("node_id")}


def format_server_status_short(status: dict[str, Any] | None) -> str:
    if not status:
        return "—"
    return (
        f"CPU {_fmt_cpu(status.get('cpu'))} · "
        f"RAM {_fmt_bytes_pair(status.get('mem'))} · "
        f"Swap {_fmt_bytes_pair(status.get('swap'))} · "
        f"Disk {_fmt_bytes_pair(status.get('disk'))}"
    )
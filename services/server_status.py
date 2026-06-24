"""Публичный статус инбаундов подписки для пользователей (/start)."""
from __future__ import annotations

import html
import re
from typing import Any

from loguru import logger

from db.bot_settings import get_inbound_public_status_map, get_subscription_inbound_ids


def _status_icon(available: bool) -> str:
    return "🟢" if available else "🔴"


_WHITELIST_LABEL_RE = re.compile(r"белые\s+списки", re.IGNORECASE)


def _user_facing_inbound_label(remark: str) -> str:
    """Публичные подписи для пользователей (цензура/нейминг в боте)."""
    return _WHITELIST_LABEL_RE.sub("Премиум подключение", remark)


async def _fetch_inbound_remarks(inbound_ids: list[int]) -> dict[int, str]:
    if not inbound_ids:
        return {}
    remarks: dict[int, str] = {}
    try:
        from db.xui_nodes import get_primary_node
        from services.panel_inbounds import fetch_inbounds_list
        from services.xui import get_api_for_node

        primary = await get_primary_node()
        if not primary:
            return {}
        api = await get_api_for_node(primary)
        for ib in await fetch_inbounds_list(api):
            iid = int(ib.id)
            if iid in inbound_ids:
                label = (getattr(ib, "remark", "") or "").strip()
                if label:
                    remarks[iid] = label
    except Exception as e:
        logger.debug("Inbound remarks fetch failed: {}", e)
    return remarks


async def list_subscription_inbounds_status() -> list[dict[str, Any]]:
    """Инбаунды из настроек подписки бота + ручной статус доступности."""
    inbound_ids = await get_subscription_inbound_ids()
    if not inbound_ids:
        return []

    status_map = await get_inbound_public_status_map()
    remarks = await _fetch_inbound_remarks(inbound_ids)

    items: list[dict[str, Any]] = []
    for inbound_id in inbound_ids:
        remark = remarks.get(inbound_id) or f"Inbound #{inbound_id}"
        items.append({
            "id": inbound_id,
            "remark": remark,
            "available": status_map.get(inbound_id, True),
        })
    return items


def _inbound_title(
    item: dict[str, Any],
    *,
    show_id: bool = False,
    for_user: bool = False,
) -> str:
    iid = item.get("id")
    remark = (item.get("remark") or "").strip()
    if for_user and remark:
        remark = _user_facing_inbound_label(remark)
    if remark and not remark.lower().startswith("inbound #"):
        title = html.escape(remark)
        if show_id:
            return f"{title} <code>(#{iid})</code>"
        return title
    return html.escape(f"Inbound #{iid}")


def format_user_server_status_text(items: list[dict[str, Any]]) -> str:
    lines = [
        "🌐 <b>Доступность серверов</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "<i>Каналы подписки VPN. Статус обновляет администратор.</i>",
        "",
    ]
    if not items:
        lines.append("<i>Инбаунды подписки не настроены.</i>")
        return "\n".join(lines)

    for item in items:
        available = bool(item.get("available", True))
        icon = _status_icon(available)
        status = "работает" if available else "временно недоступен"
        lines.append(f"{icon} {_inbound_title(item, for_user=True)} — {status}")

    return "\n".join(lines)


def format_admin_server_status_text(items: list[dict[str, Any]]) -> str:
    lines = [
        "🌐 <b>Доступность инбаундов</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Список из настроек подписки бота (📡 Inbounds).",
        "Пользователи видят его в главном меню (/start).",
        "Нажмите на канал, чтобы переключить 🟢 / 🔴.",
        "",
    ]
    if not items:
        lines.append(
            "<i>Инбаунды не заданы — укажите в Админка → Inbounds или .env</i>"
        )
        return "\n".join(lines)

    working = sum(1 for item in items if item.get("available", True))
    lines.append(f"Работает: <b>{working}</b> из <b>{len(items)}</b>")
    lines.append("")
    for item in items:
        available = bool(item.get("available", True))
        icon = _status_icon(available)
        lines.append(f"{icon} {_inbound_title(item, show_id=True)}")
    return "\n".join(lines)
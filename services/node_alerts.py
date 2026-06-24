"""Уведомления админам при смене доступности нод 3x-ui."""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from config.settings import settings
from db import xui_nodes as nodes_db

_last_known_healthy: dict[int, bool] = {}


def _short_host(host: str, max_len: int = 48) -> str:
    host = (host or "").strip()
    if len(host) <= max_len:
        return host
    return host[: max_len - 1] + "…"


def _down_text(*, node: dict[str, Any], error: Optional[str], is_primary: bool) -> str:
    name = node.get("name") or f"#{node.get('id')}"
    host = _short_host(str(node.get("host") or ""))
    err = (error or "неизвестная ошибка")[:300]
    if is_primary:
        return (
            "🔴 <b>★ Primary недоступна</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"Нода: <b>{name}</b>\n"
            f"Host: <code>{host}</code>\n"
            f"Ошибка: <code>{err}</code>\n\n"
            "<i>Бот для пользователей заблокирован до восстановления панели.</i>"
        )
    return (
        "🔴 <b>Нода недоступна</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Нода: <b>{name}</b>\n"
        f"Host: <code>{host}</code>\n"
        f"Ошибка: <code>{err}</code>\n\n"
        "<i>Синхронизация с этой панелью может не работать. Основной бот продолжает работу.</i>"
    )


def _recovery_text(*, node: dict[str, Any], is_primary: bool) -> str:
    name = node.get("name") or f"#{node.get('id')}"
    host = _short_host(str(node.get("host") or ""))
    if is_primary:
        return (
            "🟢 <b>★ Primary снова доступна</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            f"Нода: <b>{name}</b>\n"
            f"Host: <code>{host}</code>\n\n"
            "<i>Бот для пользователей разблокирован.</i>"
        )
    return (
        "🟢 <b>Нода снова доступна</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Нода: <b>{name}</b>\n"
        f"Host: <code>{host}</code>"
    )


async def _notify_admins(text: str) -> int:
    admin_ids = list(settings.BOT_ADMINS)
    if not admin_ids:
        logger.warning("Node alert skipped — BOT_ADMINS empty")
        return 0

    from bot.sender import send_message

    sent = 0
    for admin_id in admin_ids:
        try:
            await send_message(admin_id, text)
            sent += 1
        except Exception as e:
            logger.error("Node alert failed for admin {}: {}", admin_id, e)
    return sent


async def process_health_transitions(results: list[dict[str, Any]]) -> dict[str, int]:
    """
    Отправляет админам уведомления только при смене состояния ноды.
    Первый вызов после старта процесса лишь запоминает baseline без алертов.
    """
    if not results:
        return {"down": 0, "up": 0, "seeded": 0}

    primary = await nodes_db.get_primary_node()
    primary_id = int(primary["id"]) if primary and primary.get("id") else None

    down_alerts = 0
    up_alerts = 0
    seeded = 0

    for result in results:
        node_id = int(result.get("node_id") or 0)
        if not node_id:
            continue

        node = await nodes_db.get_node(node_id)
        if not node or not node.get("is_enabled"):
            if node_id in _last_known_healthy:
                del _last_known_healthy[node_id]
            continue

        now_ok = bool(result.get("ok"))
        prev_ok = _last_known_healthy.get(node_id)
        is_primary = primary_id is not None and node_id == primary_id

        if prev_ok is None:
            _last_known_healthy[node_id] = now_ok
            seeded += 1
            continue

        if prev_ok == now_ok:
            continue

        _last_known_healthy[node_id] = now_ok

        if now_ok:
            sent = await _notify_admins(_recovery_text(node=node, is_primary=is_primary))
            if sent:
                up_alerts += 1
                logger.info(
                    "Node alert: [{}] восстановлена, уведомлено админов: {}",
                    node.get("name"),
                    sent,
                )
        else:
            sent = await _notify_admins(
                _down_text(node=node, error=result.get("error"), is_primary=is_primary)
            )
            if sent:
                down_alerts += 1
                logger.warning(
                    "Node alert: [{}] недоступна, уведомлено админов: {}",
                    node.get("name"),
                    sent,
                )

    return {"down": down_alerts, "up": up_alerts, "seeded": seeded}
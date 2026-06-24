"""Публичный статус доступности серверов (нод) для пользователей."""
from __future__ import annotations

import html
from typing import Any


def _status_icon(available: bool) -> str:
    return "🟢" if available else "🔴"


def format_user_server_status_text(nodes: list[dict[str, Any]]) -> str:
    lines = [
        "🌐 <b>Доступность серверов</b>",
        "━━━━━━━━━━━━━━━━",
        "",
    ]
    if not nodes:
        lines.append("<i>Список серверов пока не настроен.</i>")
        return "\n".join(lines)

    for node in nodes:
        available = bool(int(node.get("public_available", 1)))
        icon = _status_icon(available)
        status = "работает" if available else "временно недоступен"
        star = "★ " if node.get("is_primary") else ""
        name = html.escape((node.get("name") or "—").strip())
        lines.append(f"{icon} {star}<b>{name}</b> — {status}")

    lines += ["", "<i>Статус обновляется администратором.</i>"]
    return "\n".join(lines)


def format_admin_server_status_text(nodes: list[dict[str, Any]]) -> str:
    lines = [
        "🌐 <b>Доступность серверов</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        "Пользователи видят этот статус в главном меню (/start).",
        "Нажмите на сервер, чтобы переключить 🟢 / 🔴.",
        "",
    ]
    if not nodes:
        lines.append("<i>Нет привязанных нод — добавьте в разделе «Ноды».</i>")
        return "\n".join(lines)

    working = sum(1 for n in nodes if int(n.get("public_available", 1)))
    lines.append(f"Работает: <b>{working}</b> из <b>{len(nodes)}</b>")
    lines.append("")
    for node in nodes:
        available = bool(int(node.get("public_available", 1)))
        icon = _status_icon(available)
        star = "★ " if node.get("is_primary") else ""
        name = html.escape((node.get("name") or "—").strip())
        lines.append(f"{icon} {star}{name}")
    return "\n".join(lines)
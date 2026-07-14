"""Админка: техническая диагностика системы."""
from __future__ import annotations

import time
from typing import Any

from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from services.admin_diagnostics import (
    collect_diagnostics,
    format_diagnostics_section,
    format_diagnostics_summary,
)
from ui.theme import screen
from .admin_auth import is_admin
from .admin_keyboards import diagnostics_kb
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_CACHE_TTL_SEC = 45.0
_report_cache: dict[str, Any] | None = None
_cache_at: float = 0.0

_VALID_SECTIONS = frozenset({"proc", "web", "vpn", "store", "recs"})


def _parse_diagnostics_cb(data: str) -> tuple[str, bool]:
    parts = data.split(":")
    # adm:diagnostics
    # adm:diagnostics:refresh
    # adm:diagnostics:{section}
    # adm:diagnostics:{section}:refresh
    if len(parts) == 2:
        return "summary", False
    if len(parts) == 3 and parts[2] == "refresh":
        return "summary", True
    if len(parts) == 3:
        return parts[2], False
    if len(parts) == 4 and parts[3] == "refresh":
        return parts[2], True
    return "summary", False


def _invalidate_cache() -> None:
    global _report_cache, _cache_at
    _report_cache = None
    _cache_at = 0.0


def _report_has_live_nodes(report: dict[str, Any]) -> bool:
    if report.get("live_nodes_checked"):
        return True
    return any(
        n.get("checked_live")
        for n in (report.get("nodes") or [])
        if n.get("is_enabled")
    )


async def _get_report(
    *,
    force_refresh: bool,
    view: str = "summary",
) -> dict[str, Any]:
    global _report_cache, _cache_at
    from bot import bot

    now = time.monotonic()
    needs_live = force_refresh or view == "vpn"
    cache_fresh = (
        _report_cache is not None
        and now - _cache_at <= _CACHE_TTL_SEC
    )
    if not force_refresh and cache_fresh:
        if not needs_live or _report_has_live_nodes(_report_cache):
            return _report_cache

    # Сводка — кэш БД; раздел VPN и «Обновить» — live-ноды + server/status.
    live_nodes = needs_live
    report = await collect_diagnostics(bot=bot, full_node_check=live_nodes)
    _report_cache = report
    _cache_at = now
    return report


def _format_view(report: dict[str, Any], view: str) -> str:
    if view == "summary":
        return format_diagnostics_summary(report)
    if view in _VALID_SECTIONS:
        return format_diagnostics_section(report, view)  # type: ignore[arg-type]
    return format_diagnostics_summary(report)


def _loading_text(view: str) -> str:
    labels = {
        "summary": "сводку",
        "proc": "процессы",
        "web": "webhook",
        "vpn": "VPN",
        "store": "хранилище",
        "recs": "рекомендации",
    }
    label = labels.get(view, "данные")
    return screen(
        "🔍 <b>Диагностика</b>",
        f"Проверяем {label}…",
        hint=(
            "CPU/RAM нод, webhook, процессы"
            if view == "vpn"
            else "Ноды, webhook, процессы и хранилища"
        ),
    )


async def _show_diagnostics(
    cb: CallbackQuery,
    *,
    view: str,
    refresh: bool,
) -> None:
    if refresh:
        _invalidate_cache()

    await safe_cb_answer(cb, "Обновляем…" if refresh else None)
    recs_count = len((_report_cache or {}).get("recommendations") or [])
    has_issues = not (_report_cache or {}).get("overall_ok", True)
    await send_or_edit(
        cb,
        _loading_text(view),
        diagnostics_kb(view=view, has_issues=has_issues, recs_count=recs_count),
    )

    try:
        report = await _get_report(force_refresh=refresh, view=view)
        text = _format_view(report, view)
        has_issues = not report.get("overall_ok", True)
        recs_count = len(report.get("recommendations") or [])
    except Exception as e:
        logger.exception("Admin diagnostics failed: {}", e)
        text = screen(
            "❌ <b>Ошибка диагностики</b>",
            f"<code>{type(e).__name__}: {str(e)[:200]}</code>",
        )
        has_issues = False
        recs_count = 0

    await send_or_edit(
        cb,
        text,
        diagnostics_kb(view=view, has_issues=has_issues, recs_count=recs_count),
    )


@router.callback_query(F.data == "adm:diagnostics")
async def cb_admin_diagnostics(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await _show_diagnostics(cb, view="summary", refresh=False)


@router.callback_query(F.data.startswith("adm:diagnostics"))
async def cb_admin_diagnostics_routed(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    if cb.data == "adm:diagnostics":
        return

    view, refresh = _parse_diagnostics_cb(cb.data or "")
    if view not in _VALID_SECTIONS and view != "summary":
        await safe_cb_answer(cb, "Раздел не найден", show_alert=True)
        return
    await _show_diagnostics(cb, view=view, refresh=refresh)
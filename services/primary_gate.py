"""Гейт ★ Primary: без рабочей основной ноды бот не стартует и не обслуживает пользователей."""
from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger

from db import xui_nodes as nodes_db
from services.node_alerts import process_health_transitions
from services.node_health import check_node_health

_ready: bool = False
_error: str = ""
_checked_at: float = 0.0

SERVICE_UNAVAILABLE_TEXT = (
    "⚠️ <b>Сервис временно недоступен</b>\n"
    "<i>Панель VPN на обслуживании. Попробуйте позже или напишите в поддержку.</i>"
)


def is_primary_ready() -> bool:
    return _ready


def primary_unavailable_reason() -> str:
    return _error or "Primary недоступна"


def _set_state(*, ok: bool, error: str = "") -> None:
    global _ready, _error, _checked_at
    prev = _ready
    _ready = ok
    _error = "" if ok else (error or "Primary недоступна")
    _checked_at = time.monotonic()
    if prev and not ok:
        logger.error("★ Primary недоступна — действия пользователей заблокированы: {}", _error)
    elif not prev and ok:
        logger.info("★ Primary снова доступна — сервис восстановлен")


async def _primary_node() -> Optional[dict[str, Any]]:
    primary = await nodes_db.get_primary_node()
    if not primary:
        return None
    if not int(primary.get("id") or 0):
        return None
    return primary


async def refresh_primary_ready() -> bool:
    """Проверка Primary и обновление кэша состояния."""
    primary = await _primary_node()
    if not primary:
        _set_state(ok=False, error="Основная нода не настроена в БД")
        return False
    if not primary.get("is_enabled"):
        _set_state(ok=False, error="Основная нода отключена")
        return False

    result = await check_node_health(primary)
    await process_health_transitions([result])
    if result.get("ok"):
        _set_state(ok=True)
        return True

    err = str(result.get("error") or "недоступна")[:200]
    _set_state(ok=False, error=err)
    return False


async def is_primary_operational(*, max_age_sec: float = 30.0) -> bool:
    """Кэш с TTL для middleware (не ддосить панель на каждое нажатие)."""
    if time.monotonic() - _checked_at > max_age_sec:
        await refresh_primary_ready()
    return _ready


async def ensure_primary_ready_at_startup() -> None:
    """Жёсткая проверка перед стартом процесса. Неудача → RuntimeError."""
    primary = await _primary_node()
    if not primary:
        raise RuntimeError(
            "Запуск отменён: ★ Primary нода не настроена.\n"
            "Укажите XUI_HOST в .env или добавьте ноду в БД."
        )
    if not primary.get("is_enabled"):
        raise RuntimeError(
            "Запуск отменён: ★ Primary нода отключена в реестре нод."
        )

    result = await check_node_health(primary)
    if result.get("ok"):
        _set_state(ok=True)
        logger.info(
            "★ Primary [{}] готова ({} ms)",
            primary.get("name"),
            result.get("latency_ms"),
        )
        return

    err = str(result.get("error") or "недоступна")
    _set_state(ok=False, error=err)
    raise RuntimeError(
        f"Запуск отменён: ★ Primary [{primary.get('name')}] недоступна — {err}\n"
        "Проверьте XUI_HOST, API-токен/логин и доступность панели 3x-ui."
    )


async def require_primary_for_payment() -> bool:
    """Свежая проверка перед приёмом оплаты / выдачей ключа (webhook, без кэша)."""
    return await refresh_primary_ready()


async def apply_primary_health_results(results: list[dict[str, Any]]) -> None:
    """Обновить гейт из результатов check_all_nodes_health (планировщик)."""
    primary = await _primary_node()
    if not primary:
        _set_state(ok=False, error="Основная нода не настроена в БД")
        return
    pid = int(primary["id"])
    match = next((r for r in results if int(r.get("node_id") or 0) == pid), None)
    if match and match.get("ok"):
        _set_state(ok=True)
    else:
        err = str((match or {}).get("error") or "недоступна")[:200]
        _set_state(ok=False, error=err)
"""Синхронизация подписок бота с 3x-ui. Чтение — лёгкое; запись — только repair=True."""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from db import database as db
from services.panel_cache import panel_cache
from services.xui import (
    audit_client_inbounds,
    get_panel_client_for_sync,
    repair_client_inbounds,
    get_api,
)

_SYNC_DEBOUNCE_SEC = 60.0
_last_sync_by_tg: dict[int, float] = {}


def _ms_to_iso(ms: int) -> str:
    if not ms:
        return datetime.utcnow().isoformat()
    return datetime.utcfromtimestamp(ms / 1000).isoformat()


def _iso_to_ms(iso_date: str) -> int:
    dt = datetime.fromisoformat(iso_date.replace("Z", ""))
    return int(dt.timestamp() * 1000)


def _traffic_label(gb: int) -> str:
    return "безлимит" if gb <= 0 else f"{gb} ГБ"


def _client_traffic_limit_gb(client) -> int:
    total_bytes = client.total_gb or 0
    if total_bytes <= 0:
        return 0
    return int(total_bytes / (1024 ** 3))


def _should_debounce_sync(tg_id: int) -> bool:
    now = time.monotonic()
    last = _last_sync_by_tg.get(tg_id, 0.0)
    if now - last < _SYNC_DEBOUNCE_SEC:
        return True
    _last_sync_by_tg[tg_id] = now
    return False


async def fetch_panel_client(email: str):
    return await get_panel_client_for_sync(email)


async def _auto_repair_if_needed(
    sub: Dict[str, Any], audit: dict, *, client=None,
) -> bool:
    if not audit["extra"]:
        if audit["missing_allowed"]:
            logger.warning(
                "Клиент {}: кэш показывает missing={}, attach не используем",
                sub["client_email"], audit["missing_allowed"],
            )
        return False

    db_expiry_ms = _iso_to_ms(sub["end_date"])
    if client is None:
        client = await fetch_panel_client(sub["client_email"])
    panel_expiry_ms = (client.expiry_time or 0) if client else 0
    expiry_ms = max(db_expiry_ms, panel_expiry_ms)

    sub_id = sub.get("sub_id") or ""
    if not sub_id and client and client.sub_id:
        sub_id = client.sub_id
    if not sub_id:
        logger.warning("Не удалось авто-ремонт {}: нет sub_id", sub["client_email"])
        return False

    total_gb = (sub.get("traffic_limit_gb") or 0) * 1024 * 1024 * 1024
    logger.info(
        "Авто-ремонт {}: detach extra={}",
        sub["client_email"], audit["extra"],
    )
    await repair_client_inbounds(
        sub["client_email"],
        sub_id=sub_id,
        expiry_time=expiry_ms,
        total_gb=total_gb,
    )
    return True


async def _apply_panel_to_db(sub: Dict[str, Any], client) -> Optional[Dict[str, Any]]:
    if not client:
        await db.deactivate_subscription(sub["id"])
        return None

    now_ms = int(datetime.utcnow().timestamp() * 1000)
    panel_expiry_ms = client.expiry_time or 0
    db_expiry_ms = _iso_to_ms(sub["end_date"])
    expiry_ms = max(panel_expiry_ms, db_expiry_ms)

    if not client.enable or expiry_ms <= now_ms:
        await db.deactivate_subscription(sub["id"])
        return None

    await db.update_subscription_from_panel(
        sub["id"],
        end_date=_ms_to_iso(expiry_ms),
        sub_id=client.sub_id or sub.get("sub_id"),
        is_active=True,
        traffic_limit_gb=_client_traffic_limit_gb(client),
    )
    return await db.get_subscription_by_id(sub["id"])


async def sync_subscription(
    sub: Dict[str, Any], *, repair: bool = False,
) -> Optional[Dict[str, Any]]:
    api = await get_api()
    await panel_cache.refresh(api)

    audit = await audit_client_inbounds(sub["client_email"])

    if not audit["present_allowed"] and not audit["extra"]:
        logger.info("Клиент {} удалён с панели — деактивируем #{}", sub["client_email"], sub["id"])
        await db.deactivate_subscription(sub["id"])
        return None

    client = await fetch_panel_client(sub["client_email"])

    if repair and audit["extra"]:
        await _auto_repair_if_needed(sub, audit, client=client)
        audit = await audit_client_inbounds(sub["client_email"])
        client = await fetch_panel_client(sub["client_email"])

    if not audit["present_allowed"]:
        logger.error(
            "Клиент {} отсутствует в инбаундах {}", sub["client_email"], audit["allowed"],
        )
        await db.deactivate_subscription(sub["id"])
        return None

    if audit["missing_allowed"]:
        logger.warning(
            "Клиент {} в {}/{} инбаундах (нет в {})",
            sub["client_email"],
            len(audit["present_allowed"]), len(audit["allowed"]), audit["missing_allowed"],
        )

    return await _apply_panel_to_db(sub, client)


async def sync_user_subscriptions(tg_id: int, *, repair: bool = False) -> List[Dict[str, Any]]:
    subs = await db.get_active_subscriptions(tg_id)
    synced: List[Dict[str, Any]] = []
    for sub in subs:
        updated = await sync_subscription(sub, repair=repair)
        if updated:
            synced.append(updated)
    return synced


async def get_primary_subscription_for_ui(tg_id: int) -> Optional[Dict[str, Any]]:
    """Меню и тарифы — только БД, без запросов к панели."""
    return await db.get_primary_subscription(tg_id)


async def get_active_subscriptions_for_ui(tg_id: int) -> list[dict]:
    """Все активные подписки пользователя для меню и управления."""
    return await db.get_active_subscriptions(tg_id)


async def get_primary_paid_subscription_for_ui(tg_id: int) -> Optional[dict]:
    """Платная подписка (без пробной) — для продления и оплаты."""
    return await db.get_primary_paid_subscription(tg_id)


async def get_synced_primary_subscription(
    tg_id: int, *, repair: bool = False,
) -> Optional[Dict[str, Any]]:
    """Синхронизация с панелью. repair=True — только scheduler / явный ремонт."""
    if repair or not _should_debounce_sync(tg_id):
        await sync_user_subscriptions(tg_id, repair=repair)
    return await db.get_primary_subscription(tg_id)
"""Синхронизация подписок бота с 3x-ui. Чтение — лёгкое; запись — только repair=True."""
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from db import database as db
from config.settings import settings
from services.panel_cache import get_panel_cache
from services.xui import (
    audit_client_inbounds,
    get_panel_client_for_sync,
    is_bot_client_email,
    remove_client_from_secondaries,
    repair_client_inbounds,
    get_api,
)
from utils.utc import ms_to_utc_iso, utc_iso_to_ms, utc_now_ms

_last_sync_by_tg: dict[int, float] = {}


def _ms_to_iso(ms: int) -> str:
    return ms_to_utc_iso(ms)


def _iso_to_ms(iso_date: str) -> int:
    return utc_iso_to_ms(iso_date)


def _traffic_label(gb: int) -> str:
    return "безлимит" if gb <= 0 else f"{gb} ГБ"


def _client_traffic_limit_gb(client) -> int:
    total_bytes = client.total_gb or 0
    if total_bytes <= 0:
        return 0
    return int(total_bytes / (1024 ** 3))


def _prune_last_sync_by_tg(now: float) -> None:
    """Как promo_redeem: не держать tg_id вечно (только debounce-map)."""
    if len(_last_sync_by_tg) <= 10_000:
        return
    debounce = float(settings.SUBSCRIPTION_SYNC_DEBOUNCE_SEC)
    stale_after = debounce * 20
    for tg_id, ts in list(_last_sync_by_tg.items()):
        if now - ts > stale_after:
            _last_sync_by_tg.pop(tg_id, None)


def _should_debounce_sync(tg_id: int) -> bool:
    now = time.monotonic()
    last = _last_sync_by_tg.get(tg_id, 0.0)
    if now - last < float(settings.SUBSCRIPTION_SYNC_DEBOUNCE_SEC):
        return True
    _last_sync_by_tg[tg_id] = now
    _prune_last_sync_by_tg(now)
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


async def _deactivate_after_primary_delete(sub: Dict[str, Any]) -> None:
    email = sub["client_email"]
    if not is_bot_client_email(email):
        logger.warning(
            "Пропуск каскадного удаления #{}: email {} не tg-клиент бота",
            sub["id"], email,
        )
        return
    await remove_client_from_secondaries(email)
    await db.deactivate_subscription(sub["id"])


async def _apply_panel_to_db(
    sub: Dict[str, Any],
    client,
    *,
    panel_priority: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Записать данные клиента панели в БД.
    panel_priority=False (старое): end_date = max(panel, db), disable в панели игнор.
    panel_priority=True: ★ Primary — источник истины (срок, enable, traffic, sub_id).
    """
    if not client:
        await db.deactivate_subscription(sub["id"])
        return None

    now_ms = utc_now_ms()
    panel_expiry_ms = int(client.expiry_time or 0)
    db_expiry_ms = _iso_to_ms(str(sub["end_date"]))

    if panel_priority:
        expiry_ms = panel_expiry_ms
        # На панели выключен или срок прошёл — деактивируем в БД
        if not bool(client.enable) or expiry_ms <= now_ms:
            if sub.get("is_active"):
                await db.deactivate_subscription(sub["id"])
            return None
    else:
        expiry_ms = max(panel_expiry_ms, db_expiry_ms)
        # Ручной disable в панели игнорируем — деактивируем только по expiry.
        if expiry_ms <= now_ms:
            await db.deactivate_subscription(sub["id"])
            return None

    await db.update_subscription_from_panel(
        sub["id"],
        end_date=_ms_to_iso(expiry_ms),
        sub_id=client.sub_id or sub.get("sub_id"),
        is_active=True,
        traffic_limit_gb=_client_traffic_limit_gb(client),
        clear_expiry_reminder=panel_priority,
    )
    return await db.get_subscription_by_id(sub["id"])


async def sync_subscription(
    sub: Dict[str, Any],
    *,
    repair: bool = False,
    panel_priority: bool = False,
) -> Optional[Dict[str, Any]]:
    api = await get_api()
    await get_panel_cache(api).refresh(api)

    audit = await audit_client_inbounds(sub["client_email"])

    if not audit["present_allowed"] and not audit["extra"]:
        logger.info(
            "Клиент {} удалён с основной панели — каскад на вторичные, деактивируем #{}",
            sub["client_email"], sub["id"],
        )
        await _deactivate_after_primary_delete(sub)
        return None

    client = await fetch_panel_client(sub["client_email"])

    if repair and audit["extra"]:
        await _auto_repair_if_needed(sub, audit, client=client)
        audit = await audit_client_inbounds(sub["client_email"])
        client = await fetch_panel_client(sub["client_email"])

    if not audit["present_allowed"]:
        # panel_priority: не каскадим удаление на вторичные без явного repair —
        # только деактивируем запись в БД (ручные правки / сверка).
        if panel_priority:
            logger.info(
                "Pull from panel: {} нет в инбаундах Primary — деактивируем #{}",
                sub["client_email"], sub["id"],
            )
            if sub.get("is_active"):
                await db.deactivate_subscription(sub["id"])
            return None
        logger.error(
            "Клиент {} отсутствует в инбаундах {} — каскад на вторичные",
            sub["client_email"], audit["allowed"],
        )
        await _deactivate_after_primary_delete(sub)
        return None

    if audit["missing_allowed"]:
        logger.warning(
            "Клиент {} в {}/{} инбаундах (нет в {})",
            sub["client_email"],
            len(audit["present_allowed"]), len(audit["allowed"]), audit["missing_allowed"],
        )

    return await _apply_panel_to_db(sub, client, panel_priority=panel_priority)


async def pull_all_subscriptions_from_primary() -> Dict[str, Any]:
    """
    Сверка всех активных подписок БД с ★ Primary.
    Панель — приоритет: end_date, sub_id, traffic, enable → is_active.
    Не пишет на панель (только БД).
    """
    import asyncio

    from config.settings import settings

    subs = await db.get_all_active_subscriptions()
    stats: Dict[str, Any] = {
        "total": len(subs),
        "updated": 0,
        "unchanged": 0,
        "deactivated": 0,
        "missing": 0,
        "failed": 0,
        "samples": [],  # короткие примеры изменений
    }
    if not subs:
        return stats

    # один refresh кэша на прогон
    api = await get_api()
    await get_panel_cache(api).refresh(api, force=True)

    sem = asyncio.Semaphore(settings.XUI_PANEL_CONCURRENCY)
    stats_lock = asyncio.Lock()

    async def _bump(key: str, sample: str | None = None) -> None:
        async with stats_lock:
            stats[key] = int(stats.get(key) or 0) + 1
            if sample and len(stats["samples"]) < 8:
                stats["samples"].append(sample)

    async def _one(sub: Dict[str, Any]) -> None:
        email = sub.get("client_email") or "?"
        sub_id = sub.get("id")
        before_end = str(sub.get("end_date") or "")
        before_active = bool(sub.get("is_active"))
        try:
            async with sem:
                # без повторного full refresh в каждом sync — client fetch достаточно
                client = await fetch_panel_client(email)
                if not client:
                    if before_active:
                        await db.deactivate_subscription(int(sub_id))
                        await _bump("deactivated", f"#{sub_id} {email}: нет на панели → off")
                        await _bump("missing")
                    else:
                        await _bump("unchanged")
                    return

                updated = await _apply_panel_to_db(
                    sub, client, panel_priority=True,
                )
                if updated is None:
                    await _bump(
                        "deactivated",
                        f"#{sub_id} {email}: panel enable/expiry → off",
                    )
                    return

                after_end = str(updated.get("end_date") or "")
                # сравнение с точностью до секунды
                changed = (
                    before_end[:19] != after_end[:19]
                    or (sub.get("sub_id") or "") != (updated.get("sub_id") or "")
                    or int(sub.get("traffic_limit_gb") or 0)
                    != int(updated.get("traffic_limit_gb") or 0)
                )
                if changed:
                    await _bump(
                        "updated",
                        f"#{sub_id} {email}: {before_end[:10]} → {after_end[:10]}",
                    )
                else:
                    await _bump("unchanged")
        except Exception as e:
            logger.exception("Pull from panel failed for #{} {}: {}", sub_id, email, e)
            await _bump("failed", f"#{sub_id} {email}: error {type(e).__name__}")

    await asyncio.gather(*[_one(s) for s in subs])
    logger.info(
        "Pull from Primary: total={} updated={} unchanged={} deactivated={} failed={}",
        stats["total"],
        stats["updated"],
        stats["unchanged"],
        stats["deactivated"],
        stats["failed"],
    )
    return stats


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
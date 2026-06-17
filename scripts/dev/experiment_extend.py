"""Эксперимент: продление tg-клиента и проверка панели."""
import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from db.database import extend_subscription_record, get_primary_subscription
from services.panel_cache import panel_cache
from services.xui import (
    _scan_client_inbounds,
    _unified_get_client_info,
    extend_client,
    get_api,
)

TG_ID = 123456789
EMAIL = f"tg{TG_ID}"
EXTRA_DAYS = 7


def fmt_ms(ms: int | None) -> str:
    if not ms:
        return "none"
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt_iso(iso: str) -> str:
    return iso.replace("Z", "")[:19]


async def snapshot(label: str) -> dict | None:
    sub = await get_primary_subscription(TG_ID)
    api = await get_api()
    info = await _unified_get_client_info(api, EMAIL)
    await panel_cache.refresh(api, force=True)
    located = await _scan_client_inbounds(api, EMAIL)

    print(f"\n--- {label} ---")
    if not sub:
        print("DB: подписка не найдена")
        return None

    print(f"DB end_date: {fmt_iso(sub['end_date'])}")
    if info:
        client, ibs, _ = info
        print(f"Unified get: expiry={fmt_ms(client.expiry_time)} inbounds={ibs}")
    else:
        print("Unified get: клиент не найден")

    for ib_id in sorted(located):
        client = located[ib_id]
        print(f"  inbound {ib_id}: expiry={fmt_ms(client.expiry_time)}")

    # duplicates in raw inbound list
    for ib_id in sorted(located):
        inbound = await api.inbound.get_by_id(ib_id)
        dupes = [c for c in (inbound.settings.clients or []) if c.email == EMAIL]
        if len(dupes) > 1:
            print(f"  ⚠ inbound {ib_id}: {len(dupes)} дубликатов {EMAIL}")

    return sub


async def main() -> None:
    print(f"Эксперимент продления {EMAIL} (+{EXTRA_DAYS} дн.)")

    sub = await snapshot("ДО")
    if not sub:
        return

    new_end_iso = await extend_subscription_record(sub["id"], EXTRA_DAYS)
    new_ms = int(
        datetime.fromisoformat(new_end_iso.replace("Z", ""))
        .replace(tzinfo=timezone.utc)
        .timestamp() * 1000
    )
    print(f"\nОжидаем после +{EXTRA_DAYS}д: {fmt_iso(new_end_iso)}")

    result_ms = await extend_client(EMAIL, EXTRA_DAYS, target_expiry_ms=new_ms)
    ok = abs(result_ms - new_ms) <= 1000
    print(f"extend_client: {fmt_ms(result_ms)} {'OK' if ok else 'MISMATCH'}")

    sub_after = await snapshot("ПОСЛЕ")

    api = await get_api()
    info = await _unified_get_client_info(api, EMAIL)
    if info and sub_after:
        panel_ms = info[0].expiry_time or 0
        db_ms = int(
            datetime.fromisoformat(sub_after["end_date"].replace("Z", ""))
            .replace(tzinfo=timezone.utc)
            .timestamp() * 1000
        )
        delta_h = abs(panel_ms - db_ms) / 1000 / 3600
        if delta_h < 2:
            print(f"\n✅ Панель и БД совпадают (Δ {delta_h:.1f}ч)")
        else:
            print(f"\n❌ Расхождение панель/БД: {delta_h:.1f}ч")
            print(f"   panel={fmt_ms(panel_ms)} db={fmt_ms(db_ms)}")


if __name__ == "__main__":
    asyncio.run(main())
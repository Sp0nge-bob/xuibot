"""Диагностика привязки клиента к инбаундам: unified get vs panel_cache."""
import asyncio
import secrets
import sys
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from db.bot_settings import get_subscription_inbound_ids
from services.panel_cache import panel_cache
from services.xui import (
    _clients_in_inbound_by_email,
    _confirm_inbounds_attached,
    _delete_client_by_email,
    _probe_unified_api,
    _unified_add_client,
    _unified_attach,
    _unified_get_client_info,
    ensure_bot_group,
    get_api,
)

EMAIL = "tg123456789"


async def snapshot(api, label: str, inbound_ids: list[int]) -> None:
    info = await _unified_get_client_info(api, EMAIL)
    await panel_cache.refresh(api, force=True)
    located = panel_cache.locate(EMAIL)

    unified_ids = info[1] if info else []
    cache_ids = sorted(located.keys())
    raw_ids = []
    for ib_id in inbound_ids:
        matches = await _clients_in_inbound_by_email(api, ib_id, EMAIL)
        if matches:
            raw_ids.append(ib_id)

    print(f"\n=== {label} ===")
    print(f"  unified inboundIds: {unified_ids}")
    print(f"  panel_cache:        {cache_ids}")
    print(f"  raw inbound lists:  {raw_ids}")
    missing_unified = [ib for ib in inbound_ids if ib not in unified_ids]
    missing_cache = [ib for ib in inbound_ids if ib not in located]
    missing_raw = [ib for ib in inbound_ids if ib not in raw_ids]
    if missing_unified or missing_cache or missing_raw:
        print(f"  MISSING unified={missing_unified} cache={missing_cache} raw={missing_raw}")


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    inbound_ids = await get_subscription_inbound_ids()
    unified = await _probe_unified_api(api)
    print(f"Unified API: {unified}, inbounds: {inbound_ids}")

    # cleanup
    try:
        await _delete_client_by_email(api, EMAIL)
        print(f"Deleted existing {EMAIL}")
    except Exception as e:
        print(f"Delete skip: {e}")

    await asyncio.sleep(1)

    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    sub_id = secrets.token_urlsafe(12)[:16]
    group = "telegram-bot"

    print("\n--- TEST 1: clients/add with all inboundIds ---")
    await _unified_add_client(
        api,
        email=EMAIL,
        sub_id=sub_id,
        expiry_time=expiry,
        total_gb=0,
        inbound_ids=inbound_ids,
        group=group,
    )
    await snapshot(api, "сразу после add", inbound_ids)
    await asyncio.sleep(2)
    await snapshot(api, "через 2с после add", inbound_ids)

    print("\n--- TEST 2: attach missing (per cache) ---")
    await panel_cache.refresh(api, force=True)
    located = panel_cache.locate(EMAIL)
    missing = [ib for ib in inbound_ids if ib not in located]
    if missing:
        print(f"Attaching missing per cache: {missing}")
        await _unified_attach(api, EMAIL, missing)
    await snapshot(api, "после attach", inbound_ids)

    print("\n--- TEST 3: _confirm_inbounds_attached (cache-based if patched) ---")
    try:
        await _confirm_inbounds_attached(api, EMAIL, inbound_ids, attempts=4, delay_sec=1.0)
        print("confirm: OK")
    except Exception as e:
        print(f"confirm: FAILED {e}")
    await snapshot(api, "после confirm", inbound_ids)

    # cleanup
    await _delete_client_by_email(api, EMAIL)
    print("\nCleaned up test client.")


if __name__ == "__main__":
    asyncio.run(main())
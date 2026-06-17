"""Сравнение: inbounds с одним портом vs разными портами."""
import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from services.panel_cache import panel_cache
from services.xui import (
    _clients_in_inbound_by_email,
    _delete_client_by_email,
    _unified_add_client,
    _unified_get_client_info,
    ensure_bot_group,
    get_api,
)

EMAIL = "tg_test_port"


async def test_pair(name: str, inbound_ids: list[int]) -> None:
    api = await get_api()
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.3)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)

    ports = []
    for ib in inbound_ids:
        inbound = await api.inbound.get_by_id(ib)
        ports.append(f"{ib}:p{inbound.port}")

    print(f"\n=== {name} {ports} ===")
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=inbound_ids, group="telegram-bot",
    )

    for t in (0, 3, 5, 10, 15):
        if t:
            await asyncio.sleep(t - prev)
        prev = t
        info = await _unified_get_client_info(api, EMAIL)
        u = info[1] if info else []
        raw = []
        for ib in inbound_ids:
            if await _clients_in_inbound_by_email(api, ib, EMAIL):
                raw.append(ib)
        drift = set(u) != set(raw)
        print(f"  t+{t:2d}s unified={u} raw={raw} {'DRIFT' if drift else 'ok'}")

    await _delete_client_by_email(api, EMAIL)


async def main() -> None:
    await ensure_bot_group()
    await test_pair("SAME_PORT", [1, 16])
    await test_pair("DIFF_PORTS", [1, 2])
    await test_pair("THREE_DIFF", [1, 2, 3])


if __name__ == "__main__":
    asyncio.run(main())
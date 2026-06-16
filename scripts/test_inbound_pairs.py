"""Стабильность unified inboundIds для разных пар инбаундов."""
import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from services.xui import (
    _delete_client_by_email,
    _unified_add_client,
    _unified_get_client_info,
    ensure_bot_group,
    get_api,
)

EMAIL = "tg_pair_test"
PAIRS = [
    ("1+16 same port", [1, 16]),
    ("1+17 diff port", [1, 17]),
    ("1+2 diff port", [1, 2]),
]


async def test_pair(api, name: str, ids: list[int]) -> bool:
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.3)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=ids, group="telegram-bot",
    )
    stable = True
    for t in (0, 3, 10, 20):
        if t:
            await asyncio.sleep(t - prev)
        info = await _unified_get_client_info(api, EMAIL)
        u = set(info[1]) if info else set()
        ok = u >= set(ids)
        print(f"  {name} t+{t}s unified={sorted(u)} {'ok' if ok else 'FAIL'}")
        if not ok:
            stable = False
        prev = t
    await _delete_client_by_email(api, EMAIL)
    return stable


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    for name, ids in PAIRS:
        ok = await test_pair(api, name, ids)
        print(f"  => {'STABLE' if ok else 'UNSTABLE'}\n")


if __name__ == "__main__":
    asyncio.run(main())
import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from services.xui import (
    _clients_in_inbound_by_email,
    _delete_client_by_email,
    _unified_add_client,
    _unified_get_client_info,
    ensure_bot_group,
    get_api,
)

EMAIL = "tg123456789"


async def test_ids(api, ids: list[int]) -> bool:
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(1)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=ids, group="telegram-bot",
    )
    ok = True
    prev = 0
    for t in (0, 3, 10, 20):
        if t:
            await asyncio.sleep(t - prev)
        info = await _unified_get_client_info(api, EMAIL)
        u = info[1] if info else []
        raw = [ib for ib in ids if await _clients_in_inbound_by_email(api, ib, EMAIL)]
        line_ok = set(raw) == set(ids)
        print(f"  {ids} t+{t}s unified={u} raw={raw} {'ok' if line_ok else 'FAIL'}")
        if not line_ok:
            ok = False
        prev = t
    await _delete_client_by_email(api, EMAIL)
    return ok


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    for ids in ([1, 16], [1, 2], [1, 17], [1, 2, 3]):
        print(f"\n=== {ids} ===")
        stable = await test_ids(api, ids)
        print(f"  => {'STABLE' if stable else 'UNSTABLE'}")


if __name__ == "__main__":
    asyncio.run(main())
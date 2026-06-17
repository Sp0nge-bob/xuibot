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
IDS = [1, 16]


async def dupes(api, ib: int) -> int:
    return len(await _clients_in_inbound_by_email(api, ib, EMAIL))


async def run_once(api, with_attach: bool) -> None:
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(1)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=IDS, group="telegram-bot",
    )
    if with_attach:
        from services.xui import _unified_attach
        await asyncio.sleep(0.5)
        await _unified_attach(api, EMAIL, [16])

    for t in (0, 3, 10):
        if t:
            await asyncio.sleep(t - prev)
        info = await _unified_get_client_info(api, EMAIL)
        u = info[1] if info else []
        print(
            f"  t+{t}s unified={u} dup1={await dupes(api,1)} dup16={await dupes(api,16)}"
        )
        prev = t
    await _delete_client_by_email(api, EMAIL)


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    print("=== add only ===")
    await run_once(api, False)
    await asyncio.sleep(2)
    print("=== add + attach ===")
    await run_once(api, True)


if __name__ == "__main__":
    asyncio.run(main())
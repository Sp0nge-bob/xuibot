import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from services.xui import (
    _clients_in_inbound_by_email,
    _unified_add_client,
    _unified_get_client_info,
    ensure_bot_group,
    remove_client_everywhere,
    get_api,
)

EMAIL = "tg123456789"
IDS = [1, 17]


async def main():
    api = await get_api()
    await ensure_bot_group()
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(1)
    expiry = int((datetime.utcnow() + timedelta(days=7)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=IDS, group="telegram-bot",
    )
    prev = 0
    for t in (0, 3, 10, 20):
        if t:
            await asyncio.sleep(t - prev)
        info = await _unified_get_client_info(api, EMAIL)
        u = info[1] if info else []
        raw = [ib for ib in IDS if await _clients_in_inbound_by_email(api, ib, EMAIL)]
        print(f"t+{t}s unified={u} raw={raw}")
        prev = t
    await remove_client_everywhere(EMAIL)


asyncio.run(main())
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


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.5)
    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=[1, 16], group="telegram-bot",
    )
    print("monitoring 90s...")
    for t in range(91):
        if t:
            await asyncio.sleep(1)
        info = await _unified_get_client_info(api, EMAIL)
        c16 = len(await _clients_in_inbound_by_email(api, 16, EMAIL))
        u = info[1] if info else []
        flag = " !!!" if c16 == 0 else ""
        if t <= 10 or t % 10 == 0 or c16 == 0:
            print(f"t+{t:2d}s unified={u} raw_16={c16}{flag}")
    await _delete_client_by_email(api, EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
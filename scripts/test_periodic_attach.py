import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from services.xui import (
    _delete_client_by_email,
    _unified_add_client,
    _unified_attach,
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
    info = await _unified_get_client_info(api, EMAIL)
    print(f"t+0 unified={info[1] if info else []}")

    for i in range(1, 16):
        await asyncio.sleep(2)
        await _unified_attach(api, EMAIL, [16])
        info = await _unified_get_client_info(api, EMAIL)
        u = info[1] if info else []
        print(f"t+{i*2}s attach#{i} unified={u}")
        if set(u) >= {1, 16}:
            print("STABLE early!")
            break

    await _delete_client_by_email(api, EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
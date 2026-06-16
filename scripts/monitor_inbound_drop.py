"""Мониторинг: исчезает ли клиент из inbound 16 без действий бота."""
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

EMAIL = "tg123456789"
INBOUNDS = [1, 16]


async def count_in_settings(api, ib_id: int) -> int:
    return len(await _clients_in_inbound_by_email(api, ib_id, EMAIL))


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()

    try:
        await _delete_client_by_email(api, EMAIL)
    except Exception:
        pass
    await asyncio.sleep(1)

    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    print("=== CREATE clients/add [1,16] — дальше только чтение ===\n")
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=INBOUNDS, group="telegram-bot",
    )

    for t in range(0, 31):
        if t:
            await asyncio.sleep(1)
        info = await _unified_get_client_info(api, EMAIL)
        await panel_cache.refresh(api, force=True)
        located = panel_cache.locate(EMAIL)
        c1 = await count_in_settings(api, 1)
        c16 = await count_in_settings(api, 16)
        u_ids = info[1] if info else []
        marker = ""
        if c16 == 0 and t > 0:
            marker = " <<< INBOUND 16 ПУСТ"
        print(
            f"t+{t:2d}s unified={u_ids} cache={sorted(located)} "
            f"raw_1={c1} raw_16={c16}{marker}"
        )

    await _delete_client_by_email(api, EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
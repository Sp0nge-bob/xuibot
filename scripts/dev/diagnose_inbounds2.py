"""Проверка: unified get отстаёт от panel_cache после create."""
import asyncio
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from db.bot_settings import get_subscription_inbound_ids
from services.panel_cache import panel_cache
from services.xui import (
    _delete_client_by_email,
    _unified_add_client,
    _unified_get_client_info,
    ensure_bot_group,
    get_api,
)

EMAIL = "tg_diag_test"


async def main() -> None:
    api = await get_api()
    await ensure_bot_group()
    inbound_ids = await get_subscription_inbound_ids()

    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.5)

    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=inbound_ids, group="telegram-bot",
    )

    for sec in range(0, 15, 2):
        if sec:
            await asyncio.sleep(2)
        info = await _unified_get_client_info(api, EMAIL)
        await panel_cache.refresh(api, force=True)
        u_ids = info[1] if info else []
        c_ids = sorted(panel_cache.locate(EMAIL).keys())
        drift = u_ids != c_ids
        print(f"t+{sec:2d}s unified={u_ids} cache={c_ids} {'DRIFT!' if drift else 'ok'}")

    await _delete_client_by_email(api, EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
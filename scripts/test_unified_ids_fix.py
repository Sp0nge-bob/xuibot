"""Как восстановить unified inboundIds=[1,16] после create."""
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
INBOUNDS = [1, 16]


async def snap(api, label: str) -> list[int]:
    info = await _unified_get_client_info(api, EMAIL)
    ids = info[1] if info else []
    print(f"  {label}: unified inboundIds={ids}")
    return ids


async def run_case(name: str, after_create) -> None:
    api = await get_api()
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.5)
    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    print(f"\n=== {name} ===")
    await _unified_add_client(
        api, email=EMAIL, sub_id=secrets.token_urlsafe(12)[:16],
        expiry_time=expiry, total_gb=0, inbound_ids=INBOUNDS, group="telegram-bot",
    )
    await snap(api, "t+0")
    await after_create(api)
    for sec in (1, 2, 3, 5, 10):
        await asyncio.sleep(sec if sec == 1 else sec - prev)
        prev = sec
        await snap(api, f"t+{sec}")
    await _delete_client_by_email(api, EMAIL)


async def main() -> None:
    await ensure_bot_group()

    async def noop(api):
        pass

    async def attach16(api):
        await asyncio.sleep(0.3)
        await _unified_attach(api, EMAIL, [16])
        await snap(api, "after attach")

    async def attach16_delayed(api):
        await asyncio.sleep(2)
        await _unified_attach(api, EMAIL, [16])
        await snap(api, "after delayed attach")

    await run_case("A: только add", noop)
    await run_case("B: add + attach@0.3s", attach16)
    await run_case("C: add + attach@2s", attach16_delayed)


if __name__ == "__main__":
    asyncio.run(main())
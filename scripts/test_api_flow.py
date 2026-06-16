"""Тест unified API flow (api.txt) только для tg123456789."""
import asyncio
import sys

sys.path.insert(0, ".")

from services.xui import (
    _unified_get_client_info,
    audit_client_inbounds,
    extend_client,
    get_api,
    provision_client,
    remove_client_everywhere,
)

EMAIL = "tg123456789"
TG_ID = 123456789


async def snap(label: str) -> None:
    api = await get_api()
    audit = await audit_client_inbounds(EMAIL)
    info = await _unified_get_client_info(api, EMAIL)
    u = info[1] if info else []
    print(
        f"[{label}] unified={u} audit_present={audit['present_allowed']} "
        f"missing={audit['missing_allowed']}"
    )


async def main() -> None:
    print("=== 1. cleanup clients/del ===")
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(1)

    print("=== 2. provision clients/add + attach ===")
    await provision_client(TG_ID, plan_days=30, traffic_gb=0)
    await snap("сразу")
    await asyncio.sleep(3)
    await snap("через 3с")

    print("=== 3. extend clients/update ===")
    await extend_client(EMAIL, 7)
    await snap("после +7д")

    print("=== 4. cleanup ===")
    await remove_client_everywhere(EMAIL)
    print("OK")


if __name__ == "__main__":
    asyncio.run(main())
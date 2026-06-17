"""E2E: после provision unified inboundIds=[1,16] сразу и через 3с."""
import asyncio
import sys

sys.path.insert(0, ".")

from db.bot_settings import get_subscription_inbound_ids
from services.xui import (
    _unified_get_client_info,
    audit_client_inbounds,
    provision_client,
    remove_client_everywhere,
)

TG_ID = 123456789
EMAIL = f"tg{TG_ID}"


async def check(label: str, inbound_ids: list[int]) -> bool:
    from services.xui import get_api

    audit = await audit_client_inbounds(EMAIL)
    api = await get_api()
    info = await _unified_get_client_info(api, EMAIL)
    u = set(info[1]) if info else set()
    ok = (
        not audit["missing_allowed"]
        and not audit.get("missing_unified")
        and u >= set(inbound_ids)
    )
    print(
        f"[{label}] unified={sorted(u)} audit_missing={audit['missing_allowed']} "
        f"audit_unified={audit.get('missing_unified')} => {'OK' if ok else 'FAIL'}"
    )
    return ok


async def main() -> None:
    inbound_ids = await get_subscription_inbound_ids()
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(0.5)

    await provision_client(TG_ID, plan_days=30, traffic_gb=0)
    ok0 = await check("сразу", inbound_ids)
    await asyncio.sleep(3)
    ok3 = await check("через 3с", inbound_ids)
    print("  (фоновая синхронизация attach...)")
    await asyncio.sleep(15)
    ok18 = await check("через 18с", inbound_ids)

    await remove_client_everywhere(EMAIL)
    if ok0 and ok18:
        print("\n✅ PASS (raw стабилен, unified догоняется фоном)")
    else:
        print(f"\n❌ FAIL ok0={ok0} ok3={ok3} ok18={ok18}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
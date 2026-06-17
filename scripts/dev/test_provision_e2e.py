"""E2E: первая покупка должна сразу привязать все инбаунды."""
import asyncio
import sys

sys.path.insert(0, ".")

from db.bot_settings import get_subscription_inbound_ids
from services.panel_cache import panel_cache
from services.xui import (
    _clients_in_inbound_by_email,
    _locate_client_inbounds,
    _unified_get_client_info,
    audit_client_inbounds,
    get_api,
    provision_client,
    remove_client_everywhere,
)

TG_ID = 123456789
EMAIL = f"tg{TG_ID}"


async def check(label: str, inbound_ids: list[int]) -> bool:
    api = await get_api()
    audit = await audit_client_inbounds(EMAIL)
    info = await _unified_get_client_info(api, EMAIL)
    located = await _locate_client_inbounds(api, email=EMAIL, force=True)
    unified_ids = info[1] if info else []
    cache_ids = sorted(located.keys())

    ok = (
        not audit["missing_allowed"]
        and not audit["extra"]
        and set(cache_ids) == set(inbound_ids)
    )
    print(f"\n[{label}]")
    print(f"  audit: present={audit['present_allowed']} missing={audit['missing_allowed']}")
    print(f"  unified inboundIds={unified_ids}")
    print(f"  panel_cache={cache_ids}")
    print(f"  => {'OK' if ok else 'FAIL'}")
    return ok


async def main() -> None:
    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    print(f"Target inbounds: {inbound_ids}")

    print(f"\n1. Удаление {EMAIL} (clients/del)")
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(1)

    # sanity: no leftovers
    for ib_id in inbound_ids:
        left = await _clients_in_inbound_by_email(api, ib_id, EMAIL)
        if left:
            print(f"  WARN: still in inbound {ib_id} x{len(left)}")

    print(f"\n2. provision_client (30 days)")
    email, sub_id, link = await provision_client(TG_ID, plan_days=30, traffic_gb=0)
    print(f"  email={email} subId={sub_id}")

    ok1 = await check("сразу после provision", inbound_ids)
    await asyncio.sleep(5)
    ok2 = await check("через 5с", inbound_ids)

    # unified drift — informational only
    info = await _unified_get_client_info(api, EMAIL)
    located = await _locate_client_inbounds(api, EMAIL, force=True)
    drift = (info[1] if info else []) != sorted(located.keys())
    if drift:
        print("\n  ℹ unified get отстаёт от panel_cache (ожидаемо на этой панели)")

    if ok1 and ok2:
        print("\n✅ Первая покупка: все инбаунды привязаны стабильно")
    else:
        print("\n❌ Тест провален")
        sys.exit(1)

    print(f"\n3. Cleanup {EMAIL}")
    await remove_client_everywhere(EMAIL)


if __name__ == "__main__":
    asyncio.run(main())
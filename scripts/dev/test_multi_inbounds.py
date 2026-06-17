"""E2E: provision с 4 инбаундами."""
import asyncio
import sys

sys.path.insert(0, ".")

from db.bot_settings import get_subscription_inbound_ids, set_subscription_inbound_ids
from services.xui import audit_client_inbounds, get_api, provision_client, remove_client_everywhere

TG_ID = 123456789
EMAIL = f"tg{TG_ID}"
TEST_INBOUNDS = [1, 2, 3, 16]


async def main() -> None:
    original = await get_subscription_inbound_ids()
    print(f"Original inbounds: {original}")

    await set_subscription_inbound_ids(TEST_INBOUNDS)
    print(f"Testing with: {TEST_INBOUNDS}")

    try:
        await remove_client_everywhere(EMAIL)
        await asyncio.sleep(0.5)

        email, sub_id, _ = await provision_client(TG_ID, plan_days=7, traffic_gb=0)
        print(f"Created: {email} subId={sub_id}")

        audit = await audit_client_inbounds(EMAIL)
        print(f"audit: present={audit['present_allowed']} missing={audit['missing_allowed']}")

        await asyncio.sleep(5)
        audit2 = await audit_client_inbounds(EMAIL)
        print(f"after 5s: present={audit2['present_allowed']} missing={audit2['missing_allowed']}")

        ok = (
            set(audit["present_allowed"]) == set(TEST_INBOUNDS)
            and not audit["missing_allowed"]
            and set(audit2["present_allowed"]) == set(TEST_INBOUNDS)
            and not audit2["missing_allowed"]
        )
        print("✅ OK" if ok else "❌ FAIL")
        if not ok:
            sys.exit(1)
    finally:
        await remove_client_everywhere(EMAIL)
        await set_subscription_inbound_ids(original)
        print(f"Restored inbounds: {original}")


if __name__ == "__main__":
    asyncio.run(main())
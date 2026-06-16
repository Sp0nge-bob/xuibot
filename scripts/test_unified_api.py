"""
Smoke-тест unified API 3x-ui на живой панели.
Запуск: python scripts/test_unified_api.py
"""
import asyncio
import secrets
import sys
import uuid

sys.path.insert(0, ".")

from config.settings import settings
from db.bot_settings import get_subscription_inbound_ids
from services.xui import (
    audit_client_inbounds,
    ensure_bot_group,
    get_api,
    get_panel_client_for_sync,
    provision_client,
    extend_client,
    remove_client_everywhere,
    repair_client_inbounds,
    _unified_get_client_info,
)


TEST_TG_ID = 9998887776
TEST_EMAIL = f"tg{TEST_TG_ID}"


async def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


async def cleanup(api) -> None:
    try:
        await remove_client_everywhere(TEST_EMAIL)
    except Exception:
        pass


async def main() -> None:
    print("=== Unified API smoke test ===")
    print(f"Host: {settings.XUI_HOST}")
    print(f"Group: {settings.XUI_CLIENT_GROUP}")

    api = await get_api()
    inbound_ids = await get_subscription_inbound_ids()
    print(f"Inbounds: {inbound_ids}")

    await cleanup(api)

    group = await ensure_bot_group()
    await assert_true(bool(group), f"группа {group} готова")

    print("\n1. provision_client (новый клиент)")
    email, sub_id, sub_link = await provision_client(TEST_TG_ID, plan_days=30)
    await assert_true(email == TEST_EMAIL, f"email={email}")
    await assert_true(bool(sub_id), f"sub_id={sub_id}")
    await assert_true(bool(sub_link), f"sub_link={sub_link}")

    info = await _unified_get_client_info(api, email)
    await assert_true(info is not None, "clients/get после создания")
    client, present, client_group = info
    await assert_true(set(present) == set(inbound_ids), f"inboundIds={present}")
    await assert_true(client_group == settings.XUI_CLIENT_GROUP, f"group={client_group}")

    print("\n2. extend_client")
    new_expiry = await extend_client(email, additional_days=7)
    await assert_true(new_expiry > (client.expiry_time or 0), "срок продлён")

    print("\n3. repair_client_inbounds (идемпотентность)")
    stats = await repair_client_inbounds(
        email, sub_id=sub_id, expiry_time=new_expiry, total_gb=0,
    )
    await assert_true(stats["skip"] >= len(inbound_ids), f"stats={stats}")

    print("\n4. get_panel_client_for_sync")
    synced = await get_panel_client_for_sync(email)
    await assert_true(synced is not None and synced.sub_id == sub_id, "sync client")

    print("\n5. audit_client_inbounds")
    audit = await audit_client_inbounds(email)
    await assert_true(not audit["missing_allowed"], f"missing={audit['missing_allowed']}")
    await assert_true(not audit["extra"], f"extra={audit['extra']}")

    print("\n6. remove_client_everywhere")
    removed = await remove_client_everywhere(email)
    await assert_true(set(removed) == set(inbound_ids), f"removed from {removed}")
    info_after = await _unified_get_client_info(api, email)
    await assert_true(info_after is None, "клиент удалён с панели")

    print("\n=== ALL TESTS PASSED ===")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nFAILED: {e}")
        raise
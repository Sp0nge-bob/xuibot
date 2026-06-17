"""Сравнение: прямой add vs provision_client → unified inboundIds и subLinks."""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from py3xui.api.api_base import ApiFields

from services.xui import (
    _unified_get_client_info,
    get_api,
    provision_client,
    remove_client_everywhere,
)

EMAIL = "tg123456789"
TG_ID = 123456789


async def sub_link_count(api, sub_id: str) -> tuple[list[int], int]:
    info = await _unified_get_client_info(api, EMAIL)
    unified = info[1] if info else []
    url = api.client._url(f"panel/api/clients/subLinks/{sub_id}")
    try:
        resp = await api.client._get(url, {"Accept": "application/json"})
        obj = resp.json().get(ApiFields.OBJ) or []
        count = len(obj) if isinstance(obj, list) else 0
    except Exception:
        count = -1
    return unified, count


async def main() -> None:
    api = await get_api()

    print("=== provision_client (как бот) ===")
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(1)
    _, sub_id, _ = await provision_client(TG_ID, plan_days=30)
    u, n = await sub_link_count(api, sub_id)
    print(f"  unified={u} subLinks={n}")
    await asyncio.sleep(3)
    u, n = await sub_link_count(api, sub_id)
    print(f"  через 3с unified={u} subLinks={n}")
    await remove_client_everywhere(EMAIL)

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
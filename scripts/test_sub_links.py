"""Проверка: clients/add с inboundIds [1,16] → unified inboundIds и ссылки подписки."""
import asyncio
import json
import secrets
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from py3xui.api.api_base import ApiFields

from services.xui import (
    _delete_client_by_email,
    _tg_id_from_email,
    _unified_get_client_info,
    get_api,
    remove_client_everywhere,
)

EMAIL = "tg123456789"
INBOUNDS = [1, 16]


async def fetch_sub_links(api, sub_id: str) -> list:
    for endpoint in (
        f"panel/api/clients/subLinks/{sub_id}",
        f"panel/api/clients/links/{EMAIL}",
    ):
        url = api.client._url(endpoint)
        try:
            resp = await api.client._get(url, {"Accept": "application/json"})
            data = resp.json()
            obj = data.get(ApiFields.OBJ)
            if isinstance(obj, list):
                return obj
            if isinstance(obj, dict):
                return obj.get("links") or obj.get("subs") or []
        except Exception as e:
            print(f"  {endpoint}: {e}")
    return []


async def add_minimal(api, *, with_id: bool, with_sub_id: bool) -> str:
    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    sub_id = secrets.token_urlsafe(12)[:16]
    client = {
        "email": EMAIL,
        "totalGB": 0,
        "expiryTime": expiry,
        "tgId": _tg_id_from_email(EMAIL),
        "limitIp": 0,
        "enable": True,
    }
    if with_sub_id:
        client["subId"] = sub_id
    if with_id:
        import uuid
        client["id"] = str(uuid.uuid4())

    url = api.client._url("panel/api/clients/add")
    payload = {"client": client, "inboundIds": INBOUNDS}
    print(f"  POST add payload: {json.dumps(payload, ensure_ascii=False)}")
    await api.client._post(url, {"Accept": "application/json"}, payload)
    info = await _unified_get_client_info(api, EMAIL)
    unified = info[1] if info else []
    actual_sub = (info[0].sub_id if info else None) or sub_id
    links = await fetch_sub_links(api, actual_sub)
    print(f"  unified inboundIds={unified}")
    print(f"  subLinks count={len(links)}")
    if links:
        print(f"  first link prefix={str(links[0])[:80]}...")
    return actual_sub


async def main() -> None:
    api = await get_api()
    await remove_client_everywhere(EMAIL)
    await asyncio.sleep(1)

    print("=== A: api.txt minimal (no id, no subId) ===")
    await add_minimal(api, with_id=False, with_sub_id=False)
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(1)

    print("\n=== B: minimal + subId ===")
    await add_minimal(api, with_id=False, with_sub_id=True)
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(1)

    print("\n=== C: with id + subId (текущий бот) ===")
    await add_minimal(api, with_id=True, with_sub_id=True)
    await _delete_client_by_email(api, EMAIL)
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
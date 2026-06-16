"""Какое поле в clients/add ломает unified inboundIds [1,16]."""
import asyncio
import json
import secrets
import sys
import uuid
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


async def try_add(api, client: dict, label: str) -> None:
    await _delete_client_by_email(api, EMAIL)
    await asyncio.sleep(0.5)
    payload = {"client": client, "inboundIds": INBOUNDS}
    url = api.client._url("panel/api/clients/add")
    await api.client._post(url, {"Accept": "application/json"}, payload)
    info = await _unified_get_client_info(api, EMAIL)
    unified = info[1] if info else []
    sub_id = info[0].sub_id if info else ""
    url2 = api.client._url(f"panel/api/clients/subLinks/{sub_id}")
    resp = await api.client._get(url2, {"Accept": "application/json"})
    links = resp.json().get(ApiFields.OBJ) or []
    print(f"{label}: unified={unified} subLinks={len(links)} extra={set(client)-{'email','totalGB','expiryTime','tgId','limitIp','enable'}}")


async def main() -> None:
    api = await get_api()
    await remove_client_everywhere(EMAIL)
    expiry = int((datetime.utcnow() + timedelta(days=30)).timestamp() * 1000)
    base = {
        "email": EMAIL,
        "totalGB": 0,
        "expiryTime": expiry,
        "tgId": _tg_id_from_email(EMAIL),
        "limitIp": 0,
        "enable": True,
    }

    await try_add(api, dict(base), "base")
    c = dict(base)
    c["subId"] = secrets.token_urlsafe(12)[:16]
    await try_add(api, c, "base+subId")
    c = dict(base)
    c["subId"] = secrets.token_urlsafe(12)[:16]
    c["id"] = str(uuid.uuid4())
    await try_add(api, c, "base+subId+id")
    c = dict(base)
    c["subId"] = secrets.token_urlsafe(12)[:16]
    c["flow"] = ""
    await try_add(api, c, "base+subId+flow_empty")
    c = dict(base)
    c["subId"] = secrets.token_urlsafe(12)[:16]
    c["group"] = "telegram-bot"
    await try_add(api, c, "base+subId+group")
    c = dict(base)
    c["subId"] = secrets.token_urlsafe(12)[:16]
    c["id"] = str(uuid.uuid4())
    c["flow"] = ""
    c["group"] = "telegram-bot"
    await try_add(api, c, "full_bot_payload")

    await _delete_client_by_email(api, EMAIL)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
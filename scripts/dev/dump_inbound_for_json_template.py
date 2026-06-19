"""Вывод параметров инбаундов для сборки JSON-шаблона подписки."""
import asyncio
import json
import sys

sys.path.insert(0, ".")

from config.settings import settings
from services.panel_inbounds import fetch_inbound_by_id
from services.xui import get_api


def _parse_inbound_ids() -> list[int]:
    raw = (settings.DEFAULT_SUBSCRIPTION_INBOUNDS or "").strip()
    if raw:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    return [settings.DEFAULT_INBOUND_ID]


async def _dump_raw(api, iid: int) -> None:
    from py3xui.api.api_base import ApiFields

    url = api.client._url(f"panel/api/inbounds/get/{iid}")
    resp = await api.client._get(url, {"Accept": "application/json"})
    obj = resp.json().get(ApiFields.OBJ) or {}
    raw_ss = obj.get("streamSettings") or {}
    if isinstance(raw_ss, str):
        raw_ss = json.loads(raw_ss) if raw_ss else {}
    print(f"--- raw inbound {iid}: port={obj.get('port')} network={raw_ss.get('network')} ---")
    print("wsSettings:", json.dumps(raw_ss.get("wsSettings") or {}, ensure_ascii=False))
    print("externalProxy:", json.dumps(raw_ss.get("externalProxy") or [], ensure_ascii=False))


async def main() -> None:
    api = await get_api()
    for iid in _parse_inbound_ids():
        await _dump_raw(api, iid)
        ib = await fetch_inbound_by_id(api, iid)
        if not ib:
            print(f"inbound {iid}: not found")
            continue
        ss = getattr(ib, "stream_settings", None)
        if ss is not None and hasattr(ss, "model_dump"):
            ss_data = ss.model_dump(by_alias=True)
        elif isinstance(ss, str):
            ss_data = json.loads(ss)
        else:
            ss_data = ss
        settings = getattr(ib, "settings", None)
        if settings is not None and hasattr(settings, "model_dump"):
            settings_data = settings.model_dump(by_alias=True)
        elif isinstance(settings, str):
            settings_data = json.loads(settings)
        else:
            settings_data = settings
        print(f"=== inbound id={iid} port={getattr(ib, 'port', '?')} remark={getattr(ib, 'remark', '')} proto={getattr(ib, 'protocol', '?')} ===")
        print("streamSettings:")
        print(json.dumps(ss_data, indent=2, ensure_ascii=False))
        if settings_data:
            print("settings (clients omitted):")
            slim = dict(settings_data) if isinstance(settings_data, dict) else settings_data
            if isinstance(slim, dict) and "clients" in slim:
                slim = {**slim, "clients": f"[{len(slim['clients'])} clients]"}
            print(json.dumps(slim, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
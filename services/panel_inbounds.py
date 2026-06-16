"""Безопасное чтение инбаундов — child-ноды иногда отдают null в streamSettings/sniffing."""
from __future__ import annotations

from typing import Any

from loguru import logger
from py3xui import AsyncApi
from py3xui.api.api_base import ApiFields
from py3xui.inbound import Inbound

_DEFAULT_SNIFFING: dict[str, Any] = {"enabled": False, "destOverride": []}
_DEFAULT_SETTINGS: dict[str, Any] = {"clients": [], "decryption": "", "fallbacks": []}


def normalize_inbound_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Привести ответ панели к формату, который принимает py3xui.Inbound."""
    row = dict(data)
    if row.get("streamSettings") is None:
        row["streamSettings"] = ""
    if row.get("sniffing") is None:
        row["sniffing"] = dict(_DEFAULT_SNIFFING)
    if row.get("settings") is None:
        row["settings"] = dict(_DEFAULT_SETTINGS)
    return row


def parse_inbound(data: dict[str, Any]) -> Inbound:
    return Inbound.model_validate(normalize_inbound_dict(data))


async def fetch_inbounds_list(api: AsyncApi) -> list[Inbound]:
    url = api.client._url("panel/api/inbounds/list")
    response = await api.client._get(url, {"Accept": "application/json"})
    raw = response.json().get(ApiFields.OBJ) or []
    inbounds: list[Inbound] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            inbounds.append(parse_inbound(item))
        except Exception as e:
            logger.warning(
                "Пропуск inbound #{} ({}): {}",
                item.get("id"), item.get("remark") or "?", e,
            )
    return inbounds


async def fetch_inbound_by_id(api: AsyncApi, inbound_id: int) -> Inbound:
    url = api.client._url(f"panel/api/inbounds/get/{inbound_id}")
    response = await api.client._get(url, {"Accept": "application/json"})
    obj = response.json().get(ApiFields.OBJ)
    if not isinstance(obj, dict):
        raise ValueError(f"Inbound {inbound_id} not found")
    return parse_inbound(obj)
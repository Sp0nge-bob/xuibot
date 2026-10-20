"""Read-only network counters for an admin subscription card."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from loguru import logger

from services.xui import get_api, _throttle, _is_not_found_error

NETWORK_TIMEOUT_SEC = 5.0


@dataclass(frozen=True)
class ClientNetworkData:
    status: str
    up: int | None = None
    down: int | None = None
    last_online: datetime | None = None
    fetched_at: datetime | None = None


def _counter(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Invalid traffic counter")
    return value


def _last_online(value: object) -> datetime | None:
    if value is None or value == 0:
        return None
    stamp = _counter(value)
    if stamp >= 100_000_000_000:
        stamp /= 1000
    return datetime.fromtimestamp(stamp, tz=timezone.utc)


async def get_client_network_data(email: str) -> ClientNetworkData:
    if not email:
        return ClientNetworkData(status="not_found")
    try:
        # Includes connection setup and throttling in the total request budget.
        async with asyncio.timeout(NETWORK_TIMEOUT_SEC):
            api = await get_api()
            url = api.client._url(f"panel/api/clients/traffic/{quote(email, safe='')}")
            await _throttle()
            response = await api.client._get(url, {"Accept": "application/json"})
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("success") is not True:
                raise ValueError("Unsuccessful panel response")
            obj = payload.get("obj")
            if obj is None:
                return ClientNetworkData(status="not_found")
            if not isinstance(obj, dict) or obj.get("email") != email:
                raise ValueError("Unexpected client traffic response")
            return ClientNetworkData(
                status="ok", up=_counter(obj.get("up")), down=_counter(obj.get("down")),
                last_online=_last_online(obj.get("lastOnline")),
                fetched_at=datetime.now(timezone.utc),
            )
    except Exception as exc:
        if _is_not_found_error(exc):
            return ClientNetworkData(status="not_found")
        # Do not log response bodies or exception URLs containing panel credentials.
        logger.warning("Admin client network lookup failed ({})", type(exc).__name__)
        return ClientNetworkData(status="unavailable")

"""Кэш инбаундов панели — per-host, один запрос вместо N на клиента."""
import asyncio
import time
from typing import Optional

from loguru import logger
from py3xui import AsyncApi, Client
from py3xui.inbound import Inbound

from config.settings import settings
from services.panel_inbounds import fetch_inbounds_list

_host_caches: dict[str, "PanelCache"] = {}
_email_list_cache: dict[str, tuple[float, set[str]]] = {}


class PanelCache:
    def __init__(self, ttl: float | None = None):
        self.ttl = ttl if ttl is not None else float(settings.XUI_INBOUND_CACHE_TTL)
        self._inbounds: Optional[list[Inbound]] = None
        self._index: dict[str, dict[int, Client]] = {}
        self._ts: float = 0
        self._host: str | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def api_host(api: AsyncApi) -> str:
        return (getattr(api.client, "host", None) or "").rstrip("/").lower()

    @staticmethod
    def build_index(inbounds: list[Inbound]) -> dict[str, dict[int, Client]]:
        index: dict[str, dict[int, Client]] = {}
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if client.email:
                    index.setdefault(client.email, {})[inbound.id] = client
        return index

    async def refresh(self, api: AsyncApi, *, force: bool = False) -> list[Inbound]:
        host = self.api_host(api)
        async with self._lock:
            now = time.monotonic()
            host_changed = self._host and host and self._host != host
            if (
                not force
                and not host_changed
                and self._inbounds is not None
                and (now - self._ts) < self.ttl
            ):
                return self._inbounds
            try:
                inbounds = await fetch_inbounds_list(api)
            except Exception as e:
                logger.warning(
                    "inbound.get_list недоступен на {}: {}",
                    host or "panel", e,
                )
                inbounds = []
            self._inbounds = inbounds
            self._index = self.build_index(inbounds)
            self._ts = now
            self._host = host or self._host
            return inbounds

    def invalidate(self) -> None:
        self._inbounds = None
        self._index = {}
        self._ts = 0

    def locate(self, email: str) -> dict[int, Client]:
        return dict(self._index.get(email, {}))

    def set_in_index(self, email: str, inbound_id: int, client: Client) -> None:
        self._index.setdefault(email, {})[inbound_id] = client


def get_panel_cache(api: AsyncApi) -> PanelCache:
    host = PanelCache.api_host(api) or "_default"
    cache = _host_caches.get(host)
    if cache is None:
        cache = PanelCache()
        _host_caches[host] = cache
    return cache


def invalidate_panel_cache(api: AsyncApi | None = None) -> None:
    if api is None:
        for cache in _host_caches.values():
            cache.invalidate()
        _email_list_cache.clear()
        return
    host = PanelCache.api_host(api) or "_default"
    cache = _host_caches.get(host)
    if cache:
        cache.invalidate()
    _email_list_cache.pop(host, None)


def get_cached_bot_emails(api: AsyncApi) -> set[str] | None:
    host = PanelCache.api_host(api) or "_default"
    ttl = float(settings.XUI_EMAIL_LIST_CACHE_TTL)
    entry = _email_list_cache.get(host)
    if not entry:
        return None
    ts, emails = entry
    if time.monotonic() - ts >= ttl:
        _email_list_cache.pop(host, None)
        return None
    return set(emails)


def store_cached_bot_emails(api: AsyncApi, emails: set[str]) -> None:
    host = PanelCache.api_host(api) or "_default"
    _email_list_cache[host] = (time.monotonic(), set(emails))


# Обратная совместимость для scripts/
panel_cache = PanelCache()
"""Кэш списка инбаундов панели — один запрос вместо N на каждого клиента."""
import asyncio
import time
from typing import Optional

from py3xui import AsyncApi, Client
from py3xui.inbound import Inbound

from config.settings import settings


class PanelCache:
    def __init__(self, ttl: float | None = None):
        self.ttl = ttl if ttl is not None else float(settings.XUI_INBOUND_CACHE_TTL)
        self._inbounds: Optional[list[Inbound]] = None
        self._index: dict[str, dict[int, Client]] = {}
        self._ts: float = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def build_index(inbounds: list[Inbound]) -> dict[str, dict[int, Client]]:
        index: dict[str, dict[int, Client]] = {}
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if client.email:
                    index.setdefault(client.email, {})[inbound.id] = client
        return index

    async def refresh(self, api: AsyncApi, *, force: bool = False) -> list[Inbound]:
        async with self._lock:
            now = time.monotonic()
            if not force and self._inbounds is not None and (now - self._ts) < self.ttl:
                return self._inbounds
            inbounds = await api.inbound.get_list()
            self._inbounds = inbounds
            self._index = self.build_index(inbounds)
            self._ts = now
            return inbounds

    def invalidate(self) -> None:
        self._inbounds = None
        self._index = {}
        self._ts = 0

    def locate(self, email: str) -> dict[int, Client]:
        return dict(self._index.get(email, {}))

    def set_in_index(self, email: str, inbound_id: int, client: Client) -> None:
        self._index.setdefault(email, {})[inbound_id] = client


panel_cache = PanelCache()
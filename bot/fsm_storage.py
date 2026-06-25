"""FSM storage: Redis с TTL (прод) или MemoryStorage (без REDIS_URL)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from config.settings import settings

if TYPE_CHECKING:
    from aiogram import Dispatcher

_fsm_storage: BaseStorage | None = None


async def create_fsm_storage() -> BaseStorage:
    """Создаёт backend FSM. При заданном REDIS_URL — ping и fail-fast."""
    global _fsm_storage

    url = (settings.REDIS_URL or "").strip()
    if not url:
        logger.info("FSM storage: MemoryStorage (REDIS_URL не задан)")
        storage: BaseStorage = MemoryStorage()
        _fsm_storage = storage
        return storage

    from aiogram.fsm.storage.redis import RedisStorage

    storage = RedisStorage.from_url(
        url,
        state_ttl=settings.FSM_STATE_TTL_SEC,
        data_ttl=settings.FSM_DATA_TTL_SEC,
    )
    try:
        await storage.redis.ping()
    except Exception as e:
        await storage.close()
        raise RuntimeError(
            f"REDIS_URL задан, но Redis недоступен ({url!r}): {e}. "
            "Установите redis-server или уберите REDIS_URL для MemoryStorage."
        ) from e

    logger.info(
        "FSM storage: Redis (TTL state={}s, data={}s)",
        settings.FSM_STATE_TTL_SEC,
        settings.FSM_DATA_TTL_SEC,
    )
    _fsm_storage = storage
    return storage


async def configure_dispatcher_storage(dp: Dispatcher) -> None:
    """Подменяет storage перед polling."""
    dp.fsm.storage = await create_fsm_storage()


async def close_fsm_storage() -> None:
    global _fsm_storage
    if _fsm_storage is None:
        return
    if hasattr(_fsm_storage, "close"):
        try:
            await _fsm_storage.close()
        except Exception as e:
            logger.debug("fsm storage close: {}", e)
    _fsm_storage = None
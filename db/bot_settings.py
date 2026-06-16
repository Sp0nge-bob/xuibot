"""Runtime-настройки бота (хранятся в SQLite, перекрывают .env)."""
from typing import List, Optional

import aiosqlite

from config.settings import settings
from db.database import DB_PATH

SETTING_SUBSCRIPTION_INBOUNDS = "subscription_inbounds"


async def init_bot_settings():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO bot_settings (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = CURRENT_TIMESTAMP""",
            (key, value),
        )
        await db.commit()


def _parse_inbound_ids(raw: str) -> List[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


async def get_subscription_inbound_ids() -> List[int]:
    stored = await get_setting(SETTING_SUBSCRIPTION_INBOUNDS)
    if stored and stored.strip():
        return _parse_inbound_ids(stored)
    env_raw = (settings.DEFAULT_SUBSCRIPTION_INBOUNDS or "").strip()
    if env_raw:
        return _parse_inbound_ids(env_raw)
    return [settings.DEFAULT_INBOUND_ID]


async def set_subscription_inbound_ids(inbound_ids: List[int]) -> str:
    value = ",".join(str(x) for x in inbound_ids)
    await set_setting(SETTING_SUBSCRIPTION_INBOUNDS, value)
    return value


async def get_subscription_inbounds_display() -> str:
    ids = await get_subscription_inbound_ids()
    return ", ".join(str(x) for x in ids)
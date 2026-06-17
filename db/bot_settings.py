"""Runtime-настройки бота (хранятся в SQLite, перекрывают .env)."""
from typing import List, Optional


from config.settings import settings
from db.connection import get_db

SETTING_SUBSCRIPTION_INBOUNDS = "subscription_inbounds"
SETTING_START_ANNOUNCEMENT = "start_announcement"
SETTING_START_GREETING = "start_greeting"
SETTING_SYNC_DISABLED = "sync_disabled"

_SYNC_DISABLED_TRUTHY = frozenset({"1", "true", "yes", "on"})


async def init_bot_settings():
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def get_setting(key: str) -> Optional[str]:
    async with get_db() as db:
        async with db.execute("SELECT value FROM bot_settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None


async def set_setting(key: str, value: str):
    async with get_db() as db:
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


async def get_subscription_inbound_ids_from_settings() -> List[int]:
    """Inbound IDs из bot_settings / .env — без обращения к xui_nodes."""
    stored = await get_setting(SETTING_SUBSCRIPTION_INBOUNDS)
    if stored and stored.strip():
        return _parse_inbound_ids(stored)
    env_raw = (settings.DEFAULT_SUBSCRIPTION_INBOUNDS or "").strip()
    if env_raw:
        return _parse_inbound_ids(env_raw)
    return [settings.DEFAULT_INBOUND_ID]


async def get_subscription_inbound_ids() -> List[int]:
    """Инбаунды подписки — только с ★ основной ноды (админка), иначе bot_settings / .env."""
    try:
        from db.xui_nodes import get_primary_inbound_ids
        primary_ids = await get_primary_inbound_ids()
        if primary_ids:
            return primary_ids
    except Exception:
        pass
    return await get_subscription_inbound_ids_from_settings()


async def set_subscription_inbound_ids(inbound_ids: List[int]) -> str:
    value = ",".join(str(x) for x in inbound_ids)
    await set_setting(SETTING_SUBSCRIPTION_INBOUNDS, value)
    return value


async def get_subscription_inbounds_display() -> str:
    ids = await get_subscription_inbound_ids()
    return ", ".join(str(x) for x in ids)


async def get_subscription_inbound_count() -> int:
    return len(await get_subscription_inbound_ids())


async def get_start_announcement() -> Optional[str]:
    """Произвольный текст новостей/акций для /start (не затрагивает системные блоки меню)."""
    raw = await get_setting(SETTING_START_ANNOUNCEMENT)
    if raw and raw.strip():
        return raw.strip()
    return None


async def set_start_announcement(text: str) -> None:
    await set_setting(SETTING_START_ANNOUNCEMENT, text.strip())


async def clear_start_announcement() -> None:
    await set_setting(SETTING_START_ANNOUNCEMENT, "")


async def get_start_greeting() -> Optional[str]:
    """Шаблон приветствия для /start. Плейсхолдеры: {name}, {username}, {username_line}."""
    raw = await get_setting(SETTING_START_GREETING)
    if raw and raw.strip():
        return raw.strip()
    return None


async def set_start_greeting(text: str) -> None:
    await set_setting(SETTING_START_GREETING, text.strip())


async def clear_start_greeting() -> None:
    await set_setting(SETTING_START_GREETING, "")


async def is_sync_disabled() -> bool:
    """
    Отладка: отключить только фоновую/плановую синхронизацию нод
    (старт, таймер, очередь после оплаты, кнопка «Синхронизировать вторичные»).

    Не влияет на явные операции бота: выдача/продление ключа, удаление клиента
    (remove_client_everywhere — со всех подключённых нод), disable при истечении.
    """
    raw = await get_setting(SETTING_SYNC_DISABLED)
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_sync_disabled(disabled: bool) -> None:
    await set_setting(SETTING_SYNC_DISABLED, "1" if disabled else "0")
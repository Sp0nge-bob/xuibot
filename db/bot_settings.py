"""Runtime-настройки бота (хранятся в SQLite, перекрывают .env)."""
from typing import List, Optional


from config.settings import settings
from db.connection import get_db

SETTING_SUBSCRIPTION_INBOUNDS = "subscription_inbounds"
SETTING_START_ANNOUNCEMENT = "start_announcement"
SETTING_START_GREETING = "start_greeting"
SETTING_SYNC_DISABLED = "sync_disabled"
SETTING_BACKUP_DISABLED = "backup_disabled"
SETTING_HAPP_CRYPTO_MODE = "happ_crypto_mode"
SETTING_TRIAL_LIMIT_IP = "trial_limit_ip"
SETTING_PAID_LIMIT_IP = "paid_limit_ip"
SETTING_PRIVACY_POLICY_URL = "privacy_policy_url"
SETTING_TERMS_OF_SERVICE_URL = "terms_of_service_url"

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
    return settings.subscription_inbound_ids()


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
    Отладка: отключить плановый full sync (старт + раз в сутки).
    Ручная кнопка «Синхронизировать вторичные» работает всегда.
    Параметры клиентов бот меняет только на основной; вторичные тянет панель.

    Не влияет на явные операции бота: выдача/продление ключа, удаление клиента
    (remove_client_everywhere — со всех подключённых нод), disable при истечении.
    """
    raw = await get_setting(SETTING_SYNC_DISABLED)
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_sync_disabled(disabled: bool) -> None:
    await set_setting(SETTING_SYNC_DISABLED, "1" if disabled else "0")


async def is_backup_disabled() -> bool:
    """Админка: отключить ежедневную отправку бэкапа в ЛС."""
    raw = await get_setting(SETTING_BACKUP_DISABLED)
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_backup_disabled(disabled: bool) -> None:
    await set_setting(SETTING_BACKUP_DISABLED, "1" if disabled else "0")


async def get_happ_crypto_mode() -> str | None:
    """Режим из админки; None — использовать HAPP_CRYPTO_MODE из .env."""
    from config.happ_crypto import HAPP_CRYPTO_MODES, normalize_happ_crypto_mode

    raw = await get_setting(SETTING_HAPP_CRYPTO_MODE)
    if raw is None or not str(raw).strip():
        return None
    mode = normalize_happ_crypto_mode(str(raw))
    if mode not in HAPP_CRYPTO_MODES:
        return None
    return mode


async def set_happ_crypto_mode(mode: str) -> str:
    from config.happ_crypto import HAPP_CRYPTO_MODES, normalize_happ_crypto_mode

    normalized = normalize_happ_crypto_mode(mode)
    if normalized not in HAPP_CRYPTO_MODES:
        raise ValueError(f"Неизвестный режим Happ crypto: {mode}")
    await set_setting(SETTING_HAPP_CRYPTO_MODE, normalized)
    return normalized


def _parse_limit_ip(raw: str | None, *, default: int) -> int:
    if raw is None or not str(raw).strip():
        return default
    try:
        return max(0, int(str(raw).strip()))
    except ValueError:
        return default


async def get_trial_limit_ip() -> int:
    raw = await get_setting(SETTING_TRIAL_LIMIT_IP)
    if raw is None:
        return max(0, int(settings.TRIAL_LIMIT_IP))
    return _parse_limit_ip(raw, default=max(0, int(settings.TRIAL_LIMIT_IP)))


async def get_paid_limit_ip() -> int:
    raw = await get_setting(SETTING_PAID_LIMIT_IP)
    if raw is None:
        return max(0, int(settings.PAID_LIMIT_IP))
    return _parse_limit_ip(raw, default=max(0, int(settings.PAID_LIMIT_IP)))


async def set_trial_limit_ip(value: int) -> int:
    val = max(0, int(value))
    await set_setting(SETTING_TRIAL_LIMIT_IP, str(val))
    return val


async def set_paid_limit_ip(value: int) -> int:
    val = max(0, int(value))
    await set_setting(SETTING_PAID_LIMIT_IP, str(val))
    return val


async def get_privacy_policy_url() -> str:
    from config.legal import PRIVACY_POLICY_URL

    raw = await get_setting(SETTING_PRIVACY_POLICY_URL)
    if raw and raw.strip():
        return raw.strip()
    return PRIVACY_POLICY_URL


async def get_terms_of_service_url() -> str:
    from config.legal import TERMS_OF_SERVICE_URL

    raw = await get_setting(SETTING_TERMS_OF_SERVICE_URL)
    if raw and raw.strip():
        return raw.strip()
    return TERMS_OF_SERVICE_URL


async def set_privacy_policy_url(url: str) -> str:
    value = url.strip()
    await set_setting(SETTING_PRIVACY_POLICY_URL, value)
    return value


async def set_terms_of_service_url(url: str) -> str:
    value = url.strip()
    await set_setting(SETTING_TERMS_OF_SERVICE_URL, value)
    return value


async def clear_privacy_policy_url() -> None:
    await set_setting(SETTING_PRIVACY_POLICY_URL, "")


async def clear_terms_of_service_url() -> None:
    await set_setting(SETTING_TERMS_OF_SERVICE_URL, "")
"""Runtime-настройки бота (хранятся в SQLite, перекрывают .env)."""
import json
import re
from typing import Any, List, Optional


from config.settings import settings
from db.connection import get_db

SETTING_SUBSCRIPTION_INBOUNDS = "subscription_inbounds"
SETTING_INBOUND_PUBLIC_STATUS = "inbound_public_status"
SETTING_START_ANNOUNCEMENT = "start_announcement"
SETTING_START_GREETING = "start_greeting"
SETTING_SYNC_DISABLED = "sync_disabled"
SETTING_BACKUP_DISABLED = "backup_disabled"
SETTING_BACKUP_INTERVAL = "backup_interval"
SETTING_HAPP_CRYPTO_MODE = "happ_crypto_mode"
SETTING_TRIAL_LIMIT_IP = "trial_limit_ip"
SETTING_PAID_LIMIT_IP = "paid_limit_ip"
SETTING_PRIVACY_POLICY_URL = "privacy_policy_url"
SETTING_TERMS_OF_SERVICE_URL = "terms_of_service_url"
SETTING_PAYMENT_ADMIN_NOTIFY = "payment_admin_notify_enabled"
SETTING_TEST_MODE = "test_mode"
SETTING_BOT_LOCKDOWN = "bot_lockdown"
SETTING_BOT_LOCKDOWN_WHITELIST = "bot_lockdown_whitelist"

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


async def clear_subscription_inbound_ids_override() -> None:
    """Убрать runtime-переопределение из bot_settings."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM bot_settings WHERE key = ?",
            (SETTING_SUBSCRIPTION_INBOUNDS,),
        )
        await db.commit()


async def reset_subscription_inbounds_to_env() -> str:
    """Сбросить инбаунды подписки к DEFAULT_SUBSCRIPTION_INBOUNDS из .env."""
    env_ids = settings.subscription_inbound_ids()
    await clear_subscription_inbound_ids_override()
    try:
        from db import xui_nodes as nodes_db

        primary = await nodes_db.get_primary_node()
        node_id = int((primary or {}).get("id") or 0)
        if node_id > 0:
            await nodes_db.update_node(node_id, inbound_ids=env_ids)
    except Exception:
        pass
    return ", ".join(str(x) for x in env_ids)


async def get_subscription_inbounds_display() -> str:
    ids = await get_subscription_inbound_ids()
    return ", ".join(str(x) for x in ids)


async def get_subscription_inbound_count() -> int:
    return len(await get_subscription_inbound_ids())


async def get_inbound_public_status_map() -> dict[int, bool]:
    """Ручной статус инбаундов подписки для экрана /start (по умолчанию — доступен)."""
    raw = await get_setting(SETTING_INBOUND_PUBLIC_STATUS)
    if not raw or not str(raw).strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[int, bool] = {}
    for key, val in data.items():
        try:
            result[int(key)] = bool(val)
        except (TypeError, ValueError):
            continue
    return result


async def _save_inbound_public_status_map(status: dict[int, bool]) -> None:
    payload = {str(k): int(v) for k, v in sorted(status.items())}
    await set_setting(SETTING_INBOUND_PUBLIC_STATUS, json.dumps(payload, separators=(",", ":")))


async def is_inbound_publicly_available(inbound_id: int) -> bool:
    return (await get_inbound_public_status_map()).get(int(inbound_id), True)


async def toggle_inbound_public_available(inbound_id: int) -> bool:
    inbound_id = int(inbound_id)
    status = await get_inbound_public_status_map()
    new_val = not status.get(inbound_id, True)
    status[inbound_id] = new_val
    await _save_inbound_public_status_map(status)
    return new_val


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
    """Админка: отключить автоматическую отправку бэкапа в ЛС."""
    raw = await get_setting(SETTING_BACKUP_DISABLED)
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_backup_disabled(disabled: bool) -> None:
    await set_setting(SETTING_BACKUP_DISABLED, "1" if disabled else "0")


_BACKUP_INTERVAL_RE = re.compile(
    r"^(\d+)\s*("
    r"m|min|mins|minute|minutes|"
    r"h|hr|hrs|hour|hours|"
    r"d|day|days|"
    r"w|week|weeks"
    r")$",
    re.IGNORECASE,
)
_BACKUP_UNIT_SUFFIX = {
    "m": "m", "min": "m", "mins": "m", "minute": "m", "minutes": "m",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d",
    "w": "w", "week": "w", "weeks": "w",
}
_BACKUP_MIN_MINUTES = 30
_BACKUP_MAX_MINUTES = 30 * 24 * 60


def _interval_total_minutes(amount: int, unit: str) -> int:
    if unit == "m":
        return amount
    if unit == "h":
        return amount * 60
    if unit == "d":
        return amount * 24 * 60
    if unit == "w":
        return amount * 7 * 24 * 60
    raise ValueError(unit)


def _normalize_backup_interval(value: Any) -> str | None:
    parsed = parse_backup_interval_input(str(value or ""))
    return parsed


def parse_backup_interval_input(raw: str) -> str | None:
    """
    Разбор интервала автобэкапа → нормализованная строка: 30m, 6h, 7d, 1w.
    Минимум 30m, максимум 30d.
    """
    text = (raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    match = _BACKUP_INTERVAL_RE.match(text)
    if not match:
        return None
    amount = int(match.group(1))
    if amount < 1:
        return None
    unit = _BACKUP_UNIT_SUFFIX.get(match.group(2).lower())
    if not unit:
        return None
    total = _interval_total_minutes(amount, unit)
    if total < _BACKUP_MIN_MINUTES or total > _BACKUP_MAX_MINUTES:
        return None
    return f"{amount}{unit}"


def format_backup_interval_label(interval: str) -> str:
    """30m → каждые 30 мин, 6h → каждые 6 ч."""
    match = re.match(r"^(\d+)([mhdw])$", (interval or "").strip().lower())
    if not match:
        return interval or "—"
    amount = int(match.group(1))
    unit = match.group(2)
    labels = {"m": "мин", "h": "ч", "d": "дн", "w": "нед"}
    return f"каждые {amount} {labels[unit]}"


def backup_interval_to_scheduler_kwargs(interval: str) -> dict[str, int]:
    """Строка 6h → kwargs для APScheduler interval."""
    match = re.match(r"^(\d+)([mhdw])$", interval.strip().lower())
    if not match:
        raise ValueError(f"Invalid backup interval: {interval}")
    amount = int(match.group(1))
    unit = match.group(2)
    mapping = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    return {mapping[unit]: amount}


async def get_backup_interval() -> str:
    """Интервал автобэкапа: из админки или BACKUP_INTERVAL из .env."""
    raw = await get_setting(SETTING_BACKUP_INTERVAL)
    if raw is None or not str(raw).strip():
        return _normalize_backup_interval(settings.BACKUP_INTERVAL) or "24h"
    normalized = _normalize_backup_interval(raw)
    if normalized:
        return normalized
    env_norm = _normalize_backup_interval(settings.BACKUP_INTERVAL)
    return env_norm or "24h"


async def is_backup_interval_overridden() -> bool:
    raw = await get_setting(SETTING_BACKUP_INTERVAL)
    return raw is not None and str(raw).strip() != ""


async def set_backup_interval(interval: str) -> None:
    normalized = parse_backup_interval_input(interval)
    if not normalized:
        raise ValueError(
            "Интервал от 30m до 30d. Примеры: 30m, 6h, 24h, 7d"
        )
    await set_setting(SETTING_BACKUP_INTERVAL, normalized)


async def clear_backup_interval() -> None:
    """Сбросить переопределение — снова BACKUP_INTERVAL из .env."""
    async with get_db() as db:
        await db.execute(
            "DELETE FROM bot_settings WHERE key = ?",
            (SETTING_BACKUP_INTERVAL,),
        )
        await db.commit()


async def is_payment_admin_notify_enabled() -> bool:
    """Уведомления админам об успешных оплатах (по умолчанию включены)."""
    raw = await get_setting(SETTING_PAYMENT_ADMIN_NOTIFY)
    if raw is None:
        return True
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_payment_admin_notify_enabled(enabled: bool) -> None:
    await set_setting(SETTING_PAYMENT_ADMIN_NOTIFY, "1" if enabled else "0")


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


async def is_test_mode_overridden() -> bool:
    raw = await get_setting(SETTING_TEST_MODE)
    return raw is not None and str(raw).strip() != ""


async def get_test_mode_override() -> bool | None:
    """None — использовать TEST_MODE из .env."""
    raw = await get_setting(SETTING_TEST_MODE)
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_test_mode(enabled: bool) -> None:
    await set_setting(SETTING_TEST_MODE, "1" if enabled else "0")


async def clear_test_mode_override() -> None:
    async with get_db() as db:
        await db.execute(
            "DELETE FROM bot_settings WHERE key = ?",
            (SETTING_TEST_MODE,),
        )
        await db.commit()


async def is_bot_lockdown_enabled() -> bool:
    raw = await get_setting(SETTING_BOT_LOCKDOWN)
    return (raw or "").strip().lower() in _SYNC_DISABLED_TRUTHY


async def set_bot_lockdown_enabled(enabled: bool) -> None:
    await set_setting(SETTING_BOT_LOCKDOWN, "1" if enabled else "0")


async def get_bot_lockdown_whitelist() -> List[int]:
    raw = await get_setting(SETTING_BOT_LOCKDOWN_WHITELIST)
    if not raw or not str(raw).strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    result: list[int] = []
    for item in data:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(result))


async def set_bot_lockdown_whitelist(tg_ids: List[int]) -> List[int]:
    unique = sorted({int(x) for x in tg_ids})
    await set_setting(
        SETTING_BOT_LOCKDOWN_WHITELIST,
        json.dumps(unique, separators=(",", ":")),
    )
    return unique
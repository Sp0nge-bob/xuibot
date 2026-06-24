import json
from typing import Annotated, Any, List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode


class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: str
    # NoDecode: иначе pydantic-settings парсит List как JSON и падает на "id1,id2"
    BOT_ADMINS: Annotated[List[int], NoDecode] = []

    # Platega
    PLATEGA_MERCHANT_ID: str
    PLATEGA_SECRET: str
    PLATEGA_BASE_URL: str = "https://app.platega.io"
    # ID способов оплаты Platega (docs.platega.io; уточните у менеджера)
    PLATEGA_SBP_METHOD: int = 2
    PLATEGA_ERIP_METHOD: int = 3
    PLATEGA_CARD_METHOD: int = 11
    PLATEGA_INTL_METHOD: int = 12
    PLATEGA_CRYPTO_METHOD: int = 13
    PLATEGA_RETURN_URL: str = ""
    PLATEGA_FAILED_URL: str = ""

    # 3x-ui
    # Для твоего случая (Cloudflare + nginx + маскировка под copyparty):
    # Указывай базовый HTTPS URL со secret path, БЕЗ /panel/ в конце.
    # Пример: https://node1.tvoj-domen.com/secret-path/
    # py3xui сам добавляет panel/api/... — если указать .../panel/, API вернёт HTML.
    XUI_HOST: str
    XUI_USERNAME: str = ""
    XUI_PASSWORD: str = ""
    XUI_TOKEN: str = ""

    # Нагрузка на панель 3x-ui (для 1000+ клиентов)
    XUI_PANEL_CONCURRENCY: int = 5
    XUI_INBOUND_CACHE_TTL: int = 180
    XUI_REQUEST_DELAY_MS: int = 20
    XUI_SECONDARY_SYNC_WORKERS: int = 3
    XUI_SECONDARY_SYNC_QUEUE_SIZE: int = 500
    XUI_EMAIL_LIST_CACHE_TTL: int = 120

    # Полная синхронизация нод (как кнопка в админке) — bot/scheduler.py
    FULL_SYNC_INTERVAL_HOURS: int = 24
    # Проверка истекших подписок (disable на панели) — bot/scheduler.py
    EXPIRED_CHECK_INTERVAL_HOURS: int = 1
    # Напоминание об окончании подписки (за N дней, не чаще раза в сутки)
    EXPIRY_REMINDER_ENABLED: bool = True
    EXPIRY_REMINDER_DAYS: int = 3
    EXPIRY_REMINDER_INTERVAL_HOURS: int = 24
    SUBSCRIPTION_SYNC_DEBOUNCE_SEC: int = 60

    # Пока бот настроен на одну ноду.
    # Если хочешь раздавать клиентов по 3 нодам — скажи, добавлю выбор ноды / балансировку.

    # === Подписка (важно для твоего случая) ===
    # Поскольку подписка только на главной панели и замаскирована,
    # укажи здесь базовую часть ссылки.
    # Пример: SUBSCRIPTION_BASE_URL=https://domen.com/api/v4/
    # Тогда бот будет делать ссылки вида: https://domen.com/api/v4/{sub_id}
    SUBSCRIPTION_BASE_URL: str = ""

    # Happ: шифрование — none | crypt3_local (RSA из docs) | crypt5_api
    # https://www.happ.su/main/dev-docs/crypto-link
    HAPP_CRYPTO_MODE: str = "none"
    HAPP_CRYPTO_API_URL: str = "https://crypto.happ.su/api-v2.php"
    HAPP_CRYPTO_TIMEOUT_SEC: float = 15.0

    # 3x-ui limitIp: одновременные уникальные IP (0 = без лимита)
    TRIAL_LIMIT_IP: int = 3
    PAID_LIMIT_IP: int = 5

    # ID инбаундов в подписке (через запятую). Первый — главный на ★ Primary.
    # Пример: 1,13,16,25,28
    DEFAULT_SUBSCRIPTION_INBOUNDS: str = "1"

    # Группа клиентов 3x-ui (v3.2+) — все tg* клиенты бота попадают сюда
    XUI_CLIENT_GROUP: str = "telegram-bot"

    # Webhook
    WEBHOOK_HOST: str = "0.0.0.0"
    WEBHOOK_PORT: int = 8080
    WEBHOOK_PATH: str = "/platega-webhook"
    PUBLIC_WEBHOOK_URL: str = ""
    WEBHOOK_RATE_LIMIT_PER_MIN: int = 120
    WEBHOOK_IDEMPOTENCY_TTL_SEC: int = 300
    # Параллельная обработка webhook Platega (выдача ключей) — services/fulfillment_queue.py
    FULFILLMENT_QUEUE_WORKERS: int = 2
    FULFILLMENT_QUEUE_MAX_SIZE: int = 200
    FULFILLMENT_RETRY_ATTEMPTS: int = 3
    FULFILLMENT_RETRY_DELAYS_SEC: str = "3,10,30"

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "data/logs"
    LOG_ARCHIVE_RETAIN: int = 5
    LOG_HEARTBEAT_INTERVAL_MINUTES: int = 60

    # Ежедневный бэкап БД в ЛС админам (run_bot.py + планировщик)
    BACKUP_ENABLED: bool = True
    BACKUP_HOUR_UTC: int = 3
    BACKUP_LOCAL_RETAIN: int = 5

    # Защита от наложения нажатий (двойная оплата, параллельные callback)
    BOT_ACTION_LOCK_ENABLED: bool = True
    BOT_ACTION_DEBOUNCE_SEC: float = 0.5
    BOT_ACTION_DEBOUNCE_MAX_ENTRIES: int = 5000
    PROMO_REDEEM_COOLDOWN_SEC: float = 3.0
    STALE_PENDING_ORDER_HOURS: int = 48

    # Тестовый режим (без реальной Platega)
    TEST_MODE: bool = False

    # Опасные операции в /admin → «Отладка» (сброс БД и т.п.).
    ALLOW_DEBUG_ADMIN: bool = False

    # Запускать polling внутри app.py (lifespan).
    # Продакшен: false — отдельно `python run_bot.py` + `python app.py`.
    START_BOT_IN_WEBAPP: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    @property
    def is_admin(self):
        def check(user_id: int) -> bool:
            return user_id in self.BOT_ADMINS
        return check

    @model_validator(mode="before")
    @classmethod
    def unify_inbound_env_keys(cls, data: Any) -> Any:
        """Одна переменная DEFAULT_SUBSCRIPTION_INBOUNDS; DEFAULT_INBOUND_ID — legacy alias."""
        if not isinstance(data, dict):
            return data
        sub = str(data.get("DEFAULT_SUBSCRIPTION_INBOUNDS") or "").strip()
        legacy = data.get("DEFAULT_INBOUND_ID")
        if not sub and legacy is not None and str(legacy).strip():
            data["DEFAULT_SUBSCRIPTION_INBOUNDS"] = str(legacy).strip()
        data.pop("DEFAULT_INBOUND_ID", None)
        return data

    def subscription_inbound_ids(self) -> List[int]:
        raw = (self.DEFAULT_SUBSCRIPTION_INBOUNDS or "").strip()
        if not raw:
            return [1]
        return [int(x.strip()) for x in raw.split(",") if x.strip()]

    @property
    def DEFAULT_INBOUND_ID(self) -> int:
        """Первый инбаунд из списка (совместимость со старым кодом)."""
        ids = self.subscription_inbound_ids()
        return ids[0] if ids else 1

    @field_validator("BOT_ADMINS", mode="before")
    @classmethod
    def parse_bot_admins(cls, v):
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return []
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [int(x) for x in parsed]
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []

settings = Settings()


def warn_unsafe_runtime_config() -> None:
    """Предупреждение при опасной конфигурации (TEST_MODE + production webhook)."""
    from config.logging_setup import ensure_logging
    from loguru import logger

    ensure_logging(
        "misc",
        level=settings.LOG_LEVEL,
        log_dir=settings.LOG_DIR,
        archive_retain=settings.LOG_ARCHIVE_RETAIN,
    )
    if settings.TEST_MODE and (settings.PUBLIC_WEBHOOK_URL or "").strip():
        logger.warning(
            "TEST_MODE=true при заданном PUBLIC_WEBHOOK_URL — "
            "для продакшена установите TEST_MODE=false"
        )

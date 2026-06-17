import json
from typing import Annotated, List

from pydantic import field_validator
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
    DEFAULT_INBOUND_ID: int = 1

    # Нагрузка на панель 3x-ui (для 1000+ клиентов)
    XUI_PANEL_CONCURRENCY: int = 5
    XUI_INBOUND_CACHE_TTL: int = 180
    XUI_REQUEST_DELAY_MS: int = 20
    XUI_SECONDARY_SYNC_WORKERS: int = 3
    XUI_SECONDARY_SYNC_QUEUE_SIZE: int = 500
    XUI_EMAIL_LIST_CACHE_TTL: int = 120

    # Полная синхронизация нод (как кнопка в админке) — bot/scheduler.py
    FULL_SYNC_INTERVAL_HOURS: int = 24
    SUBSCRIPTION_SYNC_DEBOUNCE_SEC: int = 60

    # Пока бот настроен на одну ноду.
    # Если хочешь раздавать клиентов по 3 нодам — скажи, добавлю выбор ноды / балансировку.

    # === Подписка (важно для твоего случая) ===
    # Поскольку подписка только на главной панели и замаскирована,
    # укажи здесь базовую часть ссылки.
    # Пример: SUBSCRIPTION_BASE_URL=https://domen.com/api/v4/
    # Тогда бот будет делать ссылки вида: https://domen.com/api/v4/{sub_id}
    SUBSCRIPTION_BASE_URL: str = ""

    # Список ID инбаундов (через запятую), которые будут включены в дефолтную подписку.
    # Это позволяет указывать по 1 инбаунду с каждой ноды (как у тебя сейчас).
    # Пример: 5,12,23
    # Формат в .env: DEFAULT_SUBSCRIPTION_INBOUNDS=5,12,23
    # Если не указано — будет использован только DEFAULT_INBOUND_ID (для совместимости).
    DEFAULT_SUBSCRIPTION_INBOUNDS: str = ""

    # Группа клиентов 3x-ui (v3.2+) — все tg* клиенты бота попадают сюда
    XUI_CLIENT_GROUP: str = "telegram-bot"

    # Webhook
    WEBHOOK_HOST: str = "0.0.0.0"
    WEBHOOK_PORT: int = 8080
    WEBHOOK_PATH: str = "/platega-webhook"
    PUBLIC_WEBHOOK_URL: str = ""
    WEBHOOK_RATE_LIMIT_PER_MIN: int = 120
    WEBHOOK_IDEMPOTENCY_TTL_SEC: int = 300
    FULFILLMENT_QUEUE_WORKERS: int = 2
    FULFILLMENT_QUEUE_MAX_SIZE: int = 200

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "data/logs"
    LOG_SESSION_RETAIN: int = 5

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
    from loguru import logger

    if settings.TEST_MODE and (settings.PUBLIC_WEBHOOK_URL or "").strip():
        logger.warning(
            "TEST_MODE=true при заданном PUBLIC_WEBHOOK_URL — "
            "для продакшена установите TEST_MODE=false"
        )


from config.logging_setup import setup_logging

setup_logging(
    level=settings.LOG_LEVEL,
    log_dir=settings.LOG_DIR,
    session_retain=settings.LOG_SESSION_RETAIN,
)
warn_unsafe_runtime_config()

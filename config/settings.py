from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List
from loguru import logger

class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: str
    BOT_ADMINS: List[int] = []

    # Platega
    PLATEGA_MERCHANT_ID: str
    PLATEGA_SECRET: str
    PLATEGA_BASE_URL: str = "https://app.platega.io"
    # ID способов оплаты Platega (уточните у менеджера; 2=СБП, 13=крипта — типичные значения)
    PLATEGA_SBP_METHOD: int = 2
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

    LOG_LEVEL: str = "INFO"
    USE_POLLING: bool = False

    # Защита от наложения нажатий (двойная оплата, параллельные callback)
    BOT_ACTION_LOCK_ENABLED: bool = True
    BOT_ACTION_DEBOUNCE_SEC: float = 0.5

    # Тестовый режим (без реальной Platega)
    # Когда True — оплата симулируется, ключи выдаются сразу.
    # Идеально для тестирования и показа менеджеру Platega до подключения.
    TEST_MODE: bool = False

    # Запускать ли Telegram-бота внутри веб-приложения (через lifespan).
    # По умолчанию True для простоты (бот стартует вместе с uvicorn).
    # Для максимальной стабильности polling-бота рекомендуется запускать его отдельно
    # через `python run_bot.py` (и поставить здесь False).
    START_BOT_IN_WEBAPP: bool = True

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
            v = v.strip()
            if not v:
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        if isinstance(v, int):
            return [v]
        if isinstance(v, list):
            return v
        return []

settings = Settings()

logger.remove()
logger.add(
    sink=lambda msg: print(msg, end=""),
    level=settings.LOG_LEVEL,
    colorize=True,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

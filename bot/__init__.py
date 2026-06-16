import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Update
from loguru import logger

from config.settings import settings
from services.xui import ensure_bot_group, log_inbound_port_conflicts
from .handlers import router as main_router
from .admin import router as admin_router
from .middlewares import ActionLockMiddleware
from .scheduler import start_scheduler
from .sender import send_message

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

@dp.update()
async def log_telegram_update(update: Update):
    """Лог для проверки, что скрипт реально получает обновления от Telegram серверов."""
    logger.info(f"📨 Received update from Telegram (api.telegram.org): {update.update_id}")

_action_lock = ActionLockMiddleware()
dp.callback_query.middleware(_action_lock)
dp.message.middleware(_action_lock)

dp.include_router(main_router)
dp.include_router(admin_router)

async def start_bot():
    """Запуск бота с подробным логированием и проверкой токена."""
    logger.info("=" * 60)
    logger.info("🚀 START_BOT: Начало установления соединения с Telegram")
    logger.info(f"   BOT_TOKEN prefix: {settings.BOT_TOKEN[:10]}...")
    logger.info(f"   Polling mode: {settings.USE_POLLING}")
    logger.info("=" * 60)

    start_scheduler()
    logger.info("✅ Scheduler started")

    try:
        group = await ensure_bot_group()
        if group:
            logger.info("✅ Группа 3x-ui готова: {}", group)
        await log_inbound_port_conflicts()
    except Exception as e:
        logger.warning("Не удалось инициализировать группу 3x-ui: {}", e)

    # Проверка токена и базовое подключение
    logger.info("🔄 Шаг 1/3: Выполняем get_me() для проверки токена...")
    try:
        me = await bot.get_me()
        logger.info(f"✅ Токен валиден! Username: @{me.username}, ID: {me.id}")
    except Exception as e:
        logger.error(f"❌ Ошибка get_me(): {type(e).__name__}: {e}")
        logger.error("Проверь BOT_TOKEN в .env и перезапусти бота.")
        return

    # Включаем подробное логирование aiogram
    import logging
    logging.getLogger("aiogram").setLevel(logging.DEBUG)
    logging.getLogger("aiohttp").setLevel(logging.DEBUG)
    logger.info("✅ DEBUG логи aiogram включены")

    logger.info("🔄 Шаг 2/3: Запускаем polling...")

    if settings.USE_POLLING:
        # Heartbeat для подтверждения, что бот жив
        async def polling_heartbeat():
            counter = 0
            while True:
                counter += 1
                logger.info(f"🔄 [HEARTBEAT #{counter}] Polling ACTIVE — бот подключен к Telegram API")
                await asyncio.sleep(30)

        asyncio.create_task(polling_heartbeat())
        logger.info("✅ Heartbeat запущен ( каждые 30 сек)")

        logger.info("🚀 Запускаем dp.start_polling()...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    else:
        logger.warning("⚠️ USE_POLLING=False — используется polling всё равно ( для простоты)")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

async def stop_bot():
    logger.info("Stopping bot...")
    await bot.session.close()

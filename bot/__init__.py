import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from config.settings import settings
from services.xui import ensure_bot_group, log_inbound_port_conflicts
from .handlers import router as main_router
from .admin import router as admin_router
from .admin_nodes import router as admin_nodes_router
from .middlewares import ActionLockMiddleware
from .scheduler import start_scheduler
from .sender import send_message

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

_action_lock = ActionLockMiddleware()
dp.callback_query.middleware(_action_lock)
dp.message.middleware(_action_lock)

dp.include_router(main_router)
dp.include_router(admin_router)
dp.include_router(admin_nodes_router)


async def start_bot():
    """Запуск бота с проверкой токена и polling."""
    logger.info("Бот запускается…")

    start_scheduler()

    try:
        import asyncio as _asyncio
        group = await _asyncio.wait_for(ensure_bot_group(), timeout=20)
        if group:
            logger.info("Группа 3x-ui: {}", group)
        await _asyncio.wait_for(log_inbound_port_conflicts(), timeout=20)
    except _asyncio.TimeoutError:
        logger.warning("Таймаут инициализации 3x-ui — бот продолжит без проверки панели")
    except Exception as e:
        logger.warning("Не удалось инициализировать группу 3x-ui: {}", e)

    try:
        me = await bot.get_me()
        logger.info("Подключён @{} ({})", me.username, me.id)
    except Exception as e:
        logger.error("Ошибка get_me(): {}: {}", type(e).__name__, e)
        logger.error("Проверь BOT_TOKEN в .env и перезапусти бота.")
        return

    if settings.LOG_LEVEL.upper() == "DEBUG":
        logging.getLogger("aiogram").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)
        logger.debug("DEBUG-логи aiogram и aiohttp включены")

    logger.info("Polling started")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


async def stop_bot():
    logger.info("Бот останавливается…")
    await bot.session.close()
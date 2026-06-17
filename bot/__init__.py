import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from config.settings import settings
from services.node_sync import start_secondary_sync_workers, stop_secondary_sync_workers
from services.xui import ensure_bot_group, log_inbound_port_conflicts
from .handlers import router as main_router
from .admin import router as admin_router
from .admin_nodes import router as admin_nodes_router
from .middlewares import ActionLockMiddleware
from .scheduler import start_scheduler, stop_scheduler
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
    import asyncio

    logger.info("Бот запускается…")

    start_scheduler()
    await start_secondary_sync_workers()

    try:
        import asyncio as _asyncio
        group = await _asyncio.wait_for(ensure_bot_group(), timeout=20)
        if group:
            logger.info("Группа 3x-ui: {}", group)
    except _asyncio.TimeoutError:
        logger.warning("Таймаут ensure_bot_group — бот продолжит без проверки группы")
    except Exception as e:
        logger.warning("ensure_bot_group: {}", e)

    try:
        import asyncio as _asyncio
        await _asyncio.wait_for(log_inbound_port_conflicts(), timeout=20)
    except _asyncio.TimeoutError:
        logger.warning("Таймаут проверки инбаундов — бот продолжит")
    except Exception as e:
        logger.warning("log_inbound_port_conflicts: {}", e)

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
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except asyncio.CancelledError:
        logger.info("Polling cancelled")
        raise


async def stop_bot():
    """Корректная остановка: workers → polling → scheduler → HTTP-сессия."""
    import asyncio

    logger.info("Бот останавливается…")
    await stop_secondary_sync_workers()

    try:
        await asyncio.wait_for(dp.stop_polling(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("stop_polling timeout — принудительное завершение")
    except Exception as e:
        logger.debug("stop_polling: {}", e)

    stop_scheduler()

    try:
        await bot.session.close()
    except Exception as e:
        logger.debug("bot.session.close: {}", e)

    logger.info("Бот остановлен")
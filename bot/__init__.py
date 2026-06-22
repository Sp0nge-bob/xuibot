import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from config.settings import settings
from services.node_startup import initialize_nodes_at_startup
from services.node_sync import start_secondary_sync_workers, stop_secondary_sync_workers
from .handlers import router as main_router
from .tickets import router as tickets_router
from .admin import router as admin_router
from .admin_tickets import router as admin_tickets_router
from .admin_debug import router as admin_debug_router
from .admin_start_text import router as admin_start_text_router
from .admin_nodes import router as admin_nodes_router
from .admin_payments import router as admin_payments_router
from .admin_backup import router as admin_backup_router
from .admin_faq import router as admin_faq_router
from .admin_happ_crypto import router as admin_happ_crypto_router
from .admin_limit_ip import router as admin_limit_ip_router
from .admin_legal import router as admin_legal_router
from .faq import router as faq_router
from .policy import router as policy_router
from .middlewares import ActionLockMiddleware
from .scheduler import run_full_nodes_sync, start_scheduler
from .sender import send_message
from .shutdown import graceful_shutdown, register_bot_task

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())

_action_lock = ActionLockMiddleware()
dp.callback_query.middleware(_action_lock)
dp.message.middleware(_action_lock)

dp.include_router(main_router)
dp.include_router(tickets_router)
dp.include_router(admin_router)
dp.include_router(admin_tickets_router)
dp.include_router(admin_debug_router)
dp.include_router(admin_start_text_router)
dp.include_router(admin_nodes_router)
dp.include_router(admin_payments_router)
dp.include_router(admin_backup_router)
dp.include_router(admin_faq_router)
dp.include_router(admin_happ_crypto_router)
dp.include_router(admin_limit_ip_router)
dp.include_router(admin_legal_router)
dp.include_router(faq_router)
dp.include_router(policy_router)


async def start_bot():
    """Запуск бота с проверкой токена и polling."""
    import asyncio

    from bot.polling_lock import acquire_polling_lock

    acquire_polling_lock()
    logger.info("Бот запускается…")
    register_bot_task(asyncio.current_task())

    start_scheduler()

    try:
        await asyncio.wait_for(initialize_nodes_at_startup(), timeout=90)
    except asyncio.TimeoutError:
        logger.warning("Node startup: таймаут 90s — бот продолжит без полной инициализации нод")
    except Exception as e:
        logger.exception("Node startup failed: {}", e)

    try:
        await run_full_nodes_sync(source="startup")
    except Exception as e:
        logger.exception("Стартовая синхронизация нод failed: {}", e)

    await start_secondary_sync_workers()

    try:
        await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.warning("delete_webhook: {}", e)

    try:
        me = await bot.get_me()
        logger.info("Подключён @{} ({})", me.username, me.id)
        from bot.commands import setup_bot_commands

        await setup_bot_commands(bot)
    except Exception as e:
        logger.error("Ошибка get_me(): {}: {}", type(e).__name__, e)
        logger.error("Проверь BOT_TOKEN в .env и перезапусти бота.")
        from bot.polling_lock import release_polling_lock

        release_polling_lock()
        return

    if settings.LOG_LEVEL.upper() == "DEBUG":
        logging.getLogger("aiogram").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)
        logger.debug("DEBUG-логи aiogram и aiohttp включены")

    logger.info("Polling started")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=False,
            polling_timeout=2,
        )
    except asyncio.CancelledError:
        logger.info("Polling cancelled")


async def stop_bot():
    """Корректная остановка (lifespan uvicorn). Ждёт shutdown по SIGINT, если уже запущен."""
    from .shutdown import _shutdown_task

    if _shutdown_task is not None and not _shutdown_task.done():
        try:
            await _shutdown_task
            return
        except Exception as e:
            logger.debug("await _shutdown_task: {}", e)
    await graceful_shutdown(reason="lifespan")
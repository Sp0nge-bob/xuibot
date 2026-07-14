import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from loguru import logger

from config.settings import settings
from services.node_startup import initialize_nodes_at_startup
from services.node_sync import start_secondary_sync_workers, stop_secondary_sync_workers
from .handlers import router as main_router
from .tickets import router as tickets_router
from .admin import router as admin_router
from .admin_menu import router as admin_menu_router
from .admin_tickets import router as admin_tickets_router
from .admin_debug import router as admin_debug_router
from .admin_lockdown import router as admin_lockdown_router
from .admin_start_text import router as admin_start_text_router
from .admin_nodes import router as admin_nodes_router
from .admin_payments import router as admin_payments_router
from .admin_backup import router as admin_backup_router
from .admin_faq import router as admin_faq_router
from .admin_happ_crypto import router as admin_happ_crypto_router
from .admin_limit_ip import router as admin_limit_ip_router
from .admin_legal import router as admin_legal_router
from .admin_diagnostics import router as admin_diagnostics_router
from .admin_reboot import router as admin_reboot_router
from .admin_server_status import router as admin_server_status_router
from .server_status import router as server_status_router
from .faq import router as faq_router
from .policy import router as policy_router
from .middlewares import ActionLockMiddleware, MaintenanceLockdownMiddleware
from services.primary_gate import ensure_primary_ready_at_startup
from .scheduler import reschedule_backup_job, run_full_nodes_sync, start_scheduler
from .sender import send_message
from .shutdown import graceful_shutdown, register_bot_task

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

_lockdown = MaintenanceLockdownMiddleware()
_action_lock = ActionLockMiddleware()
dp.callback_query.middleware(_lockdown)
dp.message.middleware(_lockdown)
dp.callback_query.middleware(_action_lock)
dp.message.middleware(_action_lock)

# /reboot — первым: приоритет над FSM и остальными handlers
dp.include_router(admin_reboot_router)
dp.include_router(main_router)
dp.include_router(server_status_router)
dp.include_router(tickets_router)
dp.include_router(admin_router)
dp.include_router(admin_menu_router)
dp.include_router(admin_tickets_router)
dp.include_router(admin_debug_router)
dp.include_router(admin_lockdown_router)
dp.include_router(admin_start_text_router)
dp.include_router(admin_nodes_router)
dp.include_router(admin_payments_router)
dp.include_router(admin_backup_router)
dp.include_router(admin_faq_router)
dp.include_router(admin_happ_crypto_router)
dp.include_router(admin_limit_ip_router)
dp.include_router(admin_legal_router)
dp.include_router(admin_diagnostics_router)
dp.include_router(admin_server_status_router)
dp.include_router(faq_router)
dp.include_router(policy_router)


async def start_bot():
    """Запуск бота с проверкой токена и polling."""
    import asyncio

    from bot.polling_lock import acquire_polling_lock

    acquire_polling_lock()
    logger.info("Бот запускается…")
    register_bot_task(asyncio.current_task())

    from bot.polling_lock import release_polling_lock

    try:
        await asyncio.wait_for(ensure_primary_ready_at_startup(), timeout=60)
    except asyncio.TimeoutError as e:
        release_polling_lock()
        raise RuntimeError(
            "Запуск отменён: таймаут проверки ★ Primary (60 с). "
            "Проверьте доступность панели 3x-ui."
        ) from e
    except RuntimeError:
        release_polling_lock()
        raise

    start_scheduler()
    await reschedule_backup_job()

    try:
        await asyncio.wait_for(initialize_nodes_at_startup(), timeout=90)
    except asyncio.TimeoutError:
        logger.warning("Node startup: таймаут 90s — вторичные ноды не полностью инициализированы")
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

    from bot.fsm_storage import configure_dispatcher_storage

    try:
        await configure_dispatcher_storage(dp)
    except RuntimeError as e:
        release_polling_lock()
        raise

    logger.info("Polling started")

    try:
        from services.reboot_notify import send_pending_reboot_notification

        await send_pending_reboot_notification(bot)
    except Exception as e:
        logger.error("Reboot startup notify failed: {}", e)

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
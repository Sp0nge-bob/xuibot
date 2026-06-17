"""Корректное завершение при SIGINT/SIGTERM (uvicorn + polling)."""
from __future__ import annotations

import asyncio
import signal
from typing import Optional

from loguru import logger

_shutdown_lock = asyncio.Lock()
_shutdown_done = False
_shutdown_task: Optional[asyncio.Task] = None
_bot_task: Optional[asyncio.Task] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None
_handlers_installed = False
_uvicorn_hook_installed = False

SHUTDOWN_WORKERS_TIMEOUT = 3.0
SHUTDOWN_POLLING_TIMEOUT = 2.0
SHUTDOWN_TASK_TIMEOUT = 5.0


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _event_loop
    _event_loop = loop


def register_bot_task(task: asyncio.Task) -> None:
    global _bot_task
    _bot_task = task


def _resolve_loop() -> Optional[asyncio.AbstractEventLoop]:
    if _event_loop is not None:
        return _event_loop
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        pass
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


def request_shutdown(reason: str) -> None:
    """Вызывается из signal handler (синхронно) — планирует async shutdown."""
    global _shutdown_task
    loop = _resolve_loop()
    if loop is None:
        logger.warning("request_shutdown: event loop недоступен ({})", reason)
        return
    if _shutdown_task is not None and not _shutdown_task.done():
        return

    def _start() -> None:
        global _shutdown_task
        _shutdown_task = asyncio.create_task(
            graceful_shutdown(reason=reason),
            name="graceful_shutdown",
        )

    if loop.is_running():
        loop.call_soon_threadsafe(_start)
    else:
        _start()


def install_uvicorn_shutdown_hook() -> None:
    """Работает и для `python app.py`, и для `uvicorn app:app`."""
    global _uvicorn_hook_installed
    if _uvicorn_hook_installed:
        return
    _uvicorn_hook_installed = True

    try:
        import uvicorn.server
    except ImportError:
        return

    Server = uvicorn.server.Server
    original = Server.handle_exit

    def handle_exit(self, sig, frame):
        logger.info("SIGINT/SIGTERM — останавливаем бота (signal {})", sig)
        request_shutdown(f"uvicorn-{sig}")
        return original(self, sig, frame)

    Server.handle_exit = handle_exit
    logger.info("Uvicorn shutdown hook: Ctrl+C остановит polling до завершения lifespan")


async def graceful_shutdown(*, reason: str = "shutdown") -> None:
    """Идемпотентная остановка; повторные вызовы ждут завершения первого."""
    global _shutdown_done, _shutdown_task

    async with _shutdown_lock:
        if _shutdown_done:
            return

        logger.info("Остановка бота ({})", reason)

        from bot.scheduler import stop_scheduler
        from bot import bot, dp

        stop_scheduler()

        if _bot_task and not _bot_task.done():
            _bot_task.cancel()
            try:
                await asyncio.wait_for(_bot_task, timeout=SHUTDOWN_TASK_TIMEOUT)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                logger.warning("bot_task не завершился за {}s", SHUTDOWN_TASK_TIMEOUT)
            except Exception as e:
                logger.debug("bot_task join: {}", e)

        try:
            await asyncio.wait_for(bot.session.close(), timeout=SHUTDOWN_POLLING_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("bot.session.close timeout ({}s)", SHUTDOWN_POLLING_TIMEOUT)
        except Exception as e:
            logger.debug("bot.session.close: {}", e)

        try:
            await asyncio.wait_for(dp.stop_polling(), timeout=1.0)
        except Exception:
            pass

        from services.node_sync import stop_secondary_sync_workers
        from services.fulfillment_queue import drain_fulfillment_queue, stop_fulfillment_workers
        from db.connection import close_connection

        try:
            await asyncio.wait_for(drain_fulfillment_queue(), timeout=SHUTDOWN_WORKERS_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Fulfillment queue drain timeout")
        except Exception as e:
            logger.debug("drain_fulfillment_queue: {}", e)

        try:
            await asyncio.wait_for(stop_fulfillment_workers(), timeout=SHUTDOWN_WORKERS_TIMEOUT)
        except Exception as e:
            logger.debug("stop_fulfillment_workers: {}", e)

        try:
            await asyncio.wait_for(
                stop_secondary_sync_workers(),
                timeout=SHUTDOWN_WORKERS_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Secondary sync workers stop timeout ({}s)",
                SHUTDOWN_WORKERS_TIMEOUT,
            )
        except Exception as e:
            logger.debug("stop_secondary_sync_workers: {}", e)

        try:
            await close_connection()
        except Exception as e:
            logger.debug("close_connection: {}", e)

        _shutdown_done = True
        logger.info("Бот остановлен ({})", reason)

    _shutdown_task = None


async def ensure_shutdown_complete(*, reason: str = "shutdown") -> None:
    """Дождаться остановки; защищено от повторного Ctrl+C во время cleanup."""
    if _shutdown_done:
        return
    if _shutdown_task is not None and not _shutdown_task.done():
        try:
            await asyncio.shield(_shutdown_task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("await _shutdown_task: {}", e)
        return
    try:
        await asyncio.shield(graceful_shutdown(reason=reason))
    except asyncio.CancelledError:
        pass


def install_shutdown_handlers() -> None:
    """Для run_bot.py (без uvicorn)."""
    global _handlers_installed
    if _handlers_installed:
        return
    _handlers_installed = True

    loop = asyncio.get_running_loop()
    bind_event_loop(loop)

    def _handler(sig: signal.Signals) -> None:
        logger.info("Получен сигнал {} — останавливаем бота", sig.name)
        request_shutdown(sig.name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler, sig)
        except (NotImplementedError, OSError, RuntimeError):
            def _fallback_handler(signum, frame, sig=sig):
                logger.info("Получен сигнал {} — останавливаем бота", sig.name)
                request_shutdown(sig.name)

            signal.signal(sig, _fallback_handler)
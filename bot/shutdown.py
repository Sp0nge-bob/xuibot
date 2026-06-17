"""Корректное завершение при SIGINT/SIGTERM (uvicorn + polling)."""
from __future__ import annotations

import asyncio
import signal
from typing import Optional

from loguru import logger

_shutdown_lock = asyncio.Lock()
_shutdown_done = False
_bot_task: Optional[asyncio.Task] = None
_handlers_installed = False

SHUTDOWN_WORKERS_TIMEOUT = 3.0
SHUTDOWN_POLLING_TIMEOUT = 3.0
SHUTDOWN_TASK_TIMEOUT = 5.0


def register_bot_task(task: asyncio.Task) -> None:
    global _bot_task
    _bot_task = task


async def graceful_shutdown(*, reason: str = "shutdown") -> None:
    """Идемпотентная остановка: scheduler → polling → workers → HTTP-сессия."""
    global _shutdown_done
    async with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    logger.info("Остановка бота ({})", reason)

    from bot.scheduler import stop_scheduler

    stop_scheduler()

    from bot import dp

    try:
        await asyncio.wait_for(dp.stop_polling(), timeout=SHUTDOWN_POLLING_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("stop_polling timeout ({}s)", SHUTDOWN_POLLING_TIMEOUT)
    except RuntimeError:
        pass
    except Exception as e:
        logger.debug("stop_polling: {}", e)

    if _bot_task and not _bot_task.done():
        _bot_task.cancel()
        try:
            await asyncio.wait_for(_bot_task, timeout=SHUTDOWN_TASK_TIMEOUT)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug("bot_task join: {}", e)

    from services.node_sync import stop_secondary_sync_workers

    try:
        await asyncio.wait_for(
            stop_secondary_sync_workers(),
            timeout=SHUTDOWN_WORKERS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("Secondary sync workers stop timeout ({}s)", SHUTDOWN_WORKERS_TIMEOUT)
    except Exception as e:
        logger.debug("stop_secondary_sync_workers: {}", e)

    from bot import bot

    try:
        await bot.session.close()
    except Exception as e:
        logger.debug("bot.session.close: {}", e)

    logger.info("Бот остановлен ({})", reason)


def request_shutdown(reason: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(graceful_shutdown(reason=reason), name="graceful_shutdown")


def install_shutdown_handlers() -> None:
    """SIGINT/SIGTERM → немедленная остановка polling и scheduler."""
    global _handlers_installed
    if _handlers_installed:
        return
    _handlers_installed = True

    loop = asyncio.get_running_loop()

    def _handler(sig: signal.Signals) -> None:
        logger.info("Получен сигнал {} — останавливаем бота", sig.name)
        request_shutdown(sig.name)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handler, sig)
        except (NotImplementedError, OSError, RuntimeError):
            def _fallback_handler(signum, frame, sig=sig):
                logger.info("Получен сигнал {} — останавливаем бота", sig.name)
                try:
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(request_shutdown, sig.name)
                except Exception:
                    pass

            signal.signal(sig, _fallback_handler)
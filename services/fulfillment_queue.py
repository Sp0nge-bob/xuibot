"""Асинхронная очередь обработки webhook — HTTP не ждёт панель и Telegram."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from services.payment_processor import PaymentProcessResult, handle_platega_status

_queue: asyncio.Queue["_WebhookJob"] | None = None
_workers_started = False
_shutdown = asyncio.Event()
_worker_tasks: list[asyncio.Task[Any]] = []


@dataclass
class _WebhookJob:
    tx_id: str
    status: str
    callback_body: dict[str, Any]


def _get_queue() -> asyncio.Queue[_WebhookJob]:
    global _queue
    if _queue is None:
        maxsize = max(1, int(settings.FULFILLMENT_QUEUE_MAX_SIZE))
        _queue = asyncio.Queue(maxsize=maxsize)
    return _queue


async def _deliver_result(tx_id: str, result: PaymentProcessResult) -> None:
    if not result.user_message:
        return
    order = await db.get_order_by_platega_tx(tx_id)
    if not order:
        return
    from bot import bot as tg_bot, send_message
    from bot.fulfillment_delivery import deliver_fulfillment
    from bot.keyboards import back_to_main_kb

    try:
        if result.photo:
            await deliver_fulfillment(
                tg_bot,
                order["tg_id"],
                text=result.user_message,
                photo=result.photo,
                setup_text=result.setup_text,
                setup_photos=result.setup_photos or None,
                reply_markup=back_to_main_kb(),
            )
        else:
            await send_message(order["tg_id"], result.user_message)
    except Exception as e:
        logger.exception("Fulfillment queue: notify failed for tx {}: {}", tx_id, e)


async def _worker() -> None:
    q = _get_queue()
    while not _shutdown.is_set():
        try:
            job = await asyncio.wait_for(q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        try:
            result = await handle_platega_status(
                job.tx_id,
                job.status,
                source="webhook_queue",
                callback_body=job.callback_body,
                notify=True,
            )
            if result.amount_mismatch:
                logger.error("Queue rejected amount mismatch for tx {}", job.tx_id)
            elif result.handled:
                await _deliver_result(job.tx_id, result)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Fulfillment queue worker failed for tx {}: {}", job.tx_id, e)
        finally:
            q.task_done()


async def start_fulfillment_workers() -> None:
    global _workers_started, _worker_tasks
    if _workers_started:
        return
    _shutdown.clear()
    _workers_started = True
    workers = max(1, int(settings.FULFILLMENT_QUEUE_WORKERS))
    _worker_tasks = [
        asyncio.create_task(_worker(), name=f"fulfillment_queue_{i}")
        for i in range(workers)
    ]
    logger.info("Fulfillment queue workers started ({})", workers)


async def stop_fulfillment_workers() -> None:
    global _workers_started, _worker_tasks
    if not _workers_started:
        return
    _shutdown.set()
    for task in _worker_tasks:
        task.cancel()
    if _worker_tasks:
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
    _worker_tasks = []
    _workers_started = False
    logger.info("Fulfillment queue workers stopped")


def enqueue_webhook_job(
    tx_id: str,
    status: str,
    callback_body: dict[str, Any],
) -> bool:
    try:
        _get_queue().put_nowait(_WebhookJob(tx_id, status, callback_body))
        return True
    except asyncio.QueueFull:
        logger.error("Fulfillment queue full — dropping tx {}", tx_id)
        return False


async def drain_fulfillment_queue(timeout: float = 30.0) -> None:
    if _queue is None:
        return
    try:
        await asyncio.wait_for(_queue.join(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Fulfillment queue drain timeout ({}s)", timeout)
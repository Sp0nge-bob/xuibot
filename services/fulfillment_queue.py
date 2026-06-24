"""Асинхронная очередь обработки webhook — HTTP не ждёт панель и Telegram."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from services.payment_processor import PaymentProcessResult, handle_platega_status
from services.webhook_guard import complete_webhook

_queue: asyncio.Queue["_WebhookJob"] | None = None
_workers_started = False
_shutdown = asyncio.Event()
_worker_tasks: list[asyncio.Task[Any]] = []


@dataclass
class _WebhookJob:
    tx_id: str
    status: str
    callback_body: dict[str, Any]


def _retry_delays() -> list[float]:
    raw = (settings.FULFILLMENT_RETRY_DELAYS_SEC or "3,10,30").strip()
    delays: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = float(part)
            if val >= 0:
                delays.append(val)
        except ValueError:
            continue
    return delays or [3.0, 10.0, 30.0]


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
    from bot.keyboards import fulfillment_success_kb

    delays = _retry_delays()
    attempts = max(1, int(settings.FULFILLMENT_RETRY_ATTEMPTS))

    for attempt in range(1, attempts + 1):
        try:
            if result.photo:
                await deliver_fulfillment(
                    tg_bot,
                    order["tg_id"],
                    text=result.user_message,
                    photo=result.photo,
                    link_message=result.link_message,
                    reply_markup=fulfillment_success_kb(),
                )
            else:
                await send_message(
                    order["tg_id"],
                    result.user_message,
                    reply_markup=fulfillment_success_kb(),
                )
            return
        except Exception as e:
            if attempt >= attempts:
                logger.exception(
                    "Fulfillment queue: notify failed for tx {} after {} attempts: {}",
                    tx_id,
                    attempts,
                    e,
                )
                return
            delay = delays[min(attempt - 1, len(delays) - 1)]
            logger.warning(
                "Fulfillment queue: notify retry {}/{} for tx {} in {:.0f}s: {}",
                attempt,
                attempts,
                tx_id,
                delay,
                e,
            )
            await asyncio.sleep(delay)


def _should_retry_job(job: _WebhookJob, result: PaymentProcessResult | None) -> bool:
    if result is not None and result.amount_mismatch:
        return False
    if (job.status or "").upper() != "CONFIRMED":
        return False
    if result is not None and result.handled:
        return False
    return True


async def _process_job(job: _WebhookJob) -> None:
    delays = _retry_delays()
    attempts = max(1, int(settings.FULFILLMENT_RETRY_ATTEMPTS))
    result: PaymentProcessResult | None = None
    success = False

    try:
        for attempt in range(1, attempts + 1):
            try:
                result = await handle_platega_status(
                    job.tx_id,
                    job.status,
                    source="webhook_queue",
                    callback_body=job.callback_body,
                    notify=True,
                )
            except Exception as e:
                if attempt >= attempts or not _should_retry_job(job, None):
                    raise
                delay = delays[min(attempt - 1, len(delays) - 1)]
                logger.warning(
                    "Fulfillment queue: worker retry {}/{} for tx {} in {:.0f}s: {}",
                    attempt,
                    attempts,
                    job.tx_id,
                    delay,
                    e,
                )
                await asyncio.sleep(delay)
                continue

            if result.amount_mismatch:
                logger.error("Queue rejected amount mismatch for tx {}", job.tx_id)
                return

            if result.handled:
                success = True
                await _deliver_result(job.tx_id, result)
                return

            if not _should_retry_job(job, result) or attempt >= attempts:
                logger.error(
                    "Fulfillment queue: unhandled tx {} status {} (attempt {}/{})",
                    job.tx_id,
                    job.status,
                    attempt,
                    attempts,
                )
                return

            delay = delays[min(attempt - 1, len(delays) - 1)]
            logger.warning(
                "Fulfillment queue: defer retry {}/{} for tx {} in {:.0f}s",
                attempt,
                attempts,
                job.tx_id,
                delay,
            )
            await asyncio.sleep(delay)
    finally:
        await complete_webhook(job.tx_id, job.status, success=success)


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
            await _process_job(job)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Fulfillment queue worker failed for tx {}: {}", job.tx_id, e)
            await complete_webhook(job.tx_id, job.status, success=False)
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


def fulfillment_workers_running() -> bool:
    return _workers_started


def fulfillment_queue_depth() -> int | None:
    if _queue is None:
        return None
    return _queue.qsize()


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
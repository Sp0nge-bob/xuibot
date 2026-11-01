"""Асинхронная очередь обработки webhook — HTTP не ждёт панель и Telegram."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from config.settings import settings
from db import database as db
from db import payment_inbox
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
    if not order or not order.get("tg_id"):
        # Заказ оформлен через веб-сайт (tg_id отсутствует)
        return
    from bot import bot as tg_bot, send_message
    from bot.fulfillment_delivery import deliver_fulfillment
    from bot.keyboards import fulfillment_success_kb

    delays = _retry_delays()
    attempts = max(1, int(settings.FULFILLMENT_RETRY_ATTEMPTS))

    sub_key = result.sub_id or result.subscription_id or order.get("subscription_id")
    happ_url = result.happ_url
    if not happ_url and sub_key:
        from services.happ_crypto import build_happ_redirect_url
        happ_url = build_happ_redirect_url(sub_key)

    incy_url = getattr(result, "incy_url", None)
    if not incy_url and sub_key:
        from services.incy_crypto import build_incy_redirect_url
        incy_url = build_incy_redirect_url(sub_key)

    sub_db_id = result.subscription_id or order.get("subscription_id")
    success_markup = fulfillment_success_kb(
        happ_url=happ_url,
        incy_url=incy_url,
        sub_id=int(sub_db_id) if sub_db_id else None,
    )

    for attempt in range(1, attempts + 1):
        try:
            if result.photo:
                await deliver_fulfillment(
                    tg_bot,
                    order["tg_id"],
                    text=result.user_message,
                    photo=result.photo,
                    link_message=result.link_message,
                    reply_markup=success_markup,
                )
            else:
                await send_message(
                    order["tg_id"],
                    result.user_message,
                    reply_markup=success_markup,
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
                type(e).__name__,
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


async def _process_job(job: _WebhookJob) -> PaymentProcessResult | None:
    delays = _retry_delays()
    attempts = max(1, int(settings.FULFILLMENT_RETRY_ATTEMPTS))
    result: PaymentProcessResult | None = None
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
            return result

        if result.handled:
            await _deliver_result(job.tx_id, result)
            return result

        if not _should_retry_job(job, result) or attempt >= attempts:
            logger.error(
                "Fulfillment queue: unhandled tx {} status {} (attempt {}/{})",
                job.tx_id,
                job.status,
                attempt,
                attempts,
            )
            return result

        delay = delays[min(attempt - 1, len(delays) - 1)]
        logger.warning(
            "Fulfillment queue: defer retry {}/{} for tx {} in {:.0f}s",
            attempt,
            attempts,
            job.tx_id,
            delay,
        )
        await asyncio.sleep(delay)
    return result


async def _renew_lease(claim: payment_inbox.InboxClaim) -> None:
    while True:
        await asyncio.sleep(30)
        if not await payment_inbox.renew_claim(claim):
            raise RuntimeError("Inbox claim ownership lost")


async def _process_claim(claim: payment_inbox.InboxClaim) -> None:
    """Renew while processing; only the current owner may acknowledge durable work."""
    job = _WebhookJob(claim.tx_id, claim.status, claim.payload)
    processing = asyncio.create_task(_process_job(job))
    heartbeat = asyncio.create_task(_renew_lease(claim))
    state, error_code = "pending", "UNHANDLED"
    try:
        done, _ = await asyncio.wait((processing, heartbeat), return_when=asyncio.FIRST_COMPLETED)
        if heartbeat in done:
            heartbeat.result()
        result = processing.result()
        if result is not None and result.amount_mismatch:
            state, error_code = "rejected", "INVALID_PAYMENT"
        elif result is not None and result.handled:
            state, error_code = "completed", None
    except asyncio.CancelledError:
        # Keep the lease on shutdown: an external request may already be in flight.
        # Another process recovers the event after its deadline, with operation idempotency.
        raise
    except Exception as error:
        error_code = "PROCESSING_FAILED"
        logger.error("Durable webhook processing failed: {}", type(error).__name__)
    finally:
        processing.cancel()
        heartbeat.cancel()
        await asyncio.gather(processing, heartbeat, return_exceptions=True)
    delay = min(300, 2 ** min(claim.attempts, 8)) if state == "pending" else 0
    await payment_inbox.finish_claim(claim, state=state, error_code=error_code, retry_delay=delay)


async def _worker() -> None:
    q = _get_queue()
    while not _shutdown.is_set():
        try:
            # Memory queue is a wakeup hint; SQLite contains the authoritative body.
            while not q.empty():
                q.get_nowait()
                q.task_done()
            claim = await payment_inbox.claim_event()
            if claim is not None:
                await _process_claim(claim)
            else:
                try:
                    await asyncio.wait_for(q.get(), timeout=1.0)
                    q.task_done()
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Durable webhook worker failed: {}", type(e).__name__)
            await asyncio.sleep(1)


async def start_fulfillment_workers() -> None:
    global _workers_started, _worker_tasks
    if _workers_started:
        return
    await payment_inbox.init_payment_inbox()
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
    # Let a short DB claim/commit handoff finish before cancellation. Pending
    # network work remains recoverable through its durable lease deadline.
    pending = set(_worker_tasks)
    if pending:
        _, pending = await asyncio.wait(pending, timeout=1.2)
    for task in pending:
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


def fulfillment_queue_status() -> dict[str, Any]:
    """Снимок очереди выдачи — для /health и диагностики из другого процесса."""
    workers_cfg = max(1, int(settings.FULFILLMENT_QUEUE_WORKERS))
    max_size = max(1, int(settings.FULFILLMENT_QUEUE_MAX_SIZE))
    alive = sum(1 for t in _worker_tasks if not t.done()) if _worker_tasks else 0
    return {
        "workers_running": _workers_started,
        "workers_configured": workers_cfg,
        "workers_alive": alive,
        "queue_depth": _queue.qsize() if _queue is not None else 0,
        "queue_max_size": max_size,
        "shutting_down": _shutdown.is_set(),
    }


def enqueue_webhook_job(
    tx_id: str,
    status: str,
    callback_body: dict[str, Any],
) -> bool:
    try:
        _get_queue().put_nowait(_WebhookJob(tx_id, status, callback_body))
        return True
    except asyncio.QueueFull:
        logger.warning("Fulfillment wakeup queue full; durable polling remains active")
        return False


async def drain_fulfillment_queue(timeout: float = 30.0) -> None:
    if _queue is None:
        return
    try:
        await asyncio.wait_for(_queue.join(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Fulfillment queue drain timeout ({}s)", timeout)

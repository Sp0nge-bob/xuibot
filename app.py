import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config.logging_setup import init_logging

init_logging("webhook")

"""
Webhook-сервер Platega (FastAPI).

Продакшен: python app.py  +  python run_bot.py (отдельный процесс).
Опционально START_BOT_IN_WEBAPP=true — polling в этом же процессе.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import settings, warn_unsafe_runtime_config

warn_unsafe_runtime_config()
from db.database import init_db
from db.connection import close_connection
from services.platega_client import verify_callback_headers
from services.webhook_guard import acquire_webhook, webhook_rate_limited
from services.fulfillment_queue import (
    drain_fulfillment_queue,
    enqueue_webhook_job,
    start_fulfillment_workers,
    stop_fulfillment_workers,
)
from services.primary_gate import (
    ensure_primary_ready_at_startup,
    primary_unavailable_reason,
    refresh_primary_ready,
)
from bot import start_bot, stop_bot
from bot.shutdown import bind_event_loop, install_uvicorn_shutdown_hook, register_bot_task

install_uvicorn_shutdown_hook()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bind_event_loop(asyncio.get_running_loop())
    await init_db()
    logger.info("Database ready")
    await ensure_primary_ready_at_startup()
    logger.info("★ Primary ready — webhook server starting")
    await start_fulfillment_workers()

    bot_task = None
    if settings.START_BOT_IN_WEBAPP:
        logger.info("START_BOT_IN_WEBAPP=true — polling в этом процессе")
        bot_task = asyncio.create_task(start_bot(), name="telegram_bot")
        register_bot_task(bot_task)
    else:
        logger.info(
            "Webhook-only mode — polling в отдельном процессе (python run_bot.py)"
        )

    yield

    logger.info("Shutting down...")
    await drain_fulfillment_queue()
    await stop_fulfillment_workers()
    if bot_task is not None:
        await stop_bot()
    await close_connection()
    logger.info("Shutdown complete")
    from config.logging_setup import shutdown_session_logging

    shutdown_session_logging(reason="webhook_shutdown")


app = FastAPI(title="VPN Platega Bot", lifespan=lifespan)


@app.get("/health")
async def health():
    if not await refresh_primary_ready():
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "primary": primary_unavailable_reason(),
            },
        )
    return {"status": "ok"}


@app.post(settings.WEBHOOK_PATH)
async def platega_webhook(
    request: Request,
    x_merchant_id: str = Header(None, alias="X-MerchantId"),
    x_secret: str = Header(None, alias="X-Secret"),
):
    """Webhook от Platega — быстрый ответ, тяжёлая работа в очереди."""
    client_ip = request.client.host if request.client else "unknown"
    if webhook_rate_limited(client_ip):
        logger.warning("Webhook rate limited from {}", client_ip)
        raise HTTPException(status_code=429, detail="Too many requests")

    body = await request.json()
    headers = dict(request.headers)

    if not await verify_callback_headers(headers):
        logger.warning("Invalid Platega callback headers")
        raise HTTPException(status_code=401, detail="Unauthorized")

    tx_id = body.get("id")
    status = body.get("status")
    payment_method = body.get("paymentMethod")

    if not tx_id or not status:
        return JSONResponse({"ok": True})

    if not await acquire_webhook(tx_id, status):
        logger.debug("Duplicate webhook ignored: {} {}", tx_id, status)
        return JSONResponse({"ok": True})

    logger.debug("Platega callback body: {}", body)
    logger.info(
        "Platega callback: tx={} status={} method={}",
        tx_id,
        status,
        payment_method,
    )

    if not enqueue_webhook_job(tx_id, status, body):
        logger.error("Webhook queue saturated for tx {}", tx_id)

    return JSONResponse({"ok": True})


async def _run_server() -> None:
    import uvicorn

    bind_event_loop(asyncio.get_running_loop())
    config = uvicorn.Config(
        app,
        host=settings.WEBHOOK_HOST,
        port=settings.WEBHOOK_PORT,
        reload=False,
        lifespan="on",
        timeout_graceful_shutdown=8,
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(_run_server())
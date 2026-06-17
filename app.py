import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

"""
Основной файл приложения.
Запускает FastAPI (для webhook Platega) + lifespan с aiogram ботом.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import settings
from db.database import init_db
from db.connection import close_connection
from services.platega_client import verify_callback_headers
from services.webhook_guard import is_duplicate_webhook, webhook_rate_limited
from services.fulfillment_queue import (
    drain_fulfillment_queue,
    enqueue_webhook_job,
    start_fulfillment_workers,
    stop_fulfillment_workers,
)
from bot import start_bot, stop_bot
from bot.shutdown import bind_event_loop, install_uvicorn_shutdown_hook, register_bot_task

install_uvicorn_shutdown_hook()


@asynccontextmanager
async def lifespan(app: FastAPI):
    bind_event_loop(asyncio.get_running_loop())
    await init_db()
    logger.info("Database ready")
    await start_fulfillment_workers()

    logger.info("Creating bot background task (polling will start in background)...")
    bot_task = asyncio.create_task(start_bot(), name="telegram_bot")
    register_bot_task(bot_task)

    yield

    logger.info("Shutting down...")
    await drain_fulfillment_queue()
    await stop_fulfillment_workers()
    await stop_bot()
    await close_connection()
    logger.info("Shutdown complete")


app = FastAPI(title="VPN Platega Bot", lifespan=lifespan)


@app.get("/health")
async def health():
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

    if is_duplicate_webhook(tx_id, status):
        logger.debug("Duplicate webhook ignored: {} {}", tx_id, status)
        return JSONResponse({"ok": True})

    logger.info("Platega callback received: {}", body)

    if payment_method is not None:
        logger.info("Platega callback paymentMethod={} for tx {}", payment_method, tx_id)

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
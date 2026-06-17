import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

"""
Основной файл приложения.
Запускает FastAPI (для webhook Platega) + lifespan с aiogram ботом.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from loguru import logger

from config.settings import settings
from db.database import init_db
from services.platega_client import verify_callback_headers
from services.payment_processor import handle_platega_status
from db import database as db
from bot import start_bot, stop_bot, bot as tg_bot, send_message
from bot.keyboards import back_to_main_kb

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database ready")

    logger.info("🚀 Creating bot background task (polling will start in background)...")
    bot_task = asyncio.create_task(start_bot())

    yield

    logger.info("Shutting down...")
    await stop_bot()
    if not bot_task.done():
        bot_task.cancel()
    try:
        await asyncio.wait_for(bot_task, timeout=8.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception as e:
        logger.debug("bot_task join: {}", e)
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
    """Webhook от Platega."""
    body = await request.json()
    headers = dict(request.headers)

    if not await verify_callback_headers(headers):
        logger.warning("Invalid Platega callback headers")
        raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info("Platega callback received: {}", body)

    tx_id = body.get("id")
    status = body.get("status")
    payment_method = body.get("paymentMethod")

    if not tx_id or not status:
        return JSONResponse({"ok": True})

    if payment_method is not None:
        logger.info("Platega callback paymentMethod={} for tx {}", payment_method, tx_id)

    result = await handle_platega_status(
        tx_id,
        status,
        source="webhook",
        callback_body=body,
        notify=True,
    )

    if result.amount_mismatch:
        logger.error("Webhook rejected: amount mismatch for tx {}", tx_id)
        return JSONResponse({"ok": True})

    if result.handled and result.user_message:
        order = await db.get_order_by_platega_tx(tx_id)
        if order:
            try:
                if result.photo:
                    await tg_bot.send_photo(
                        order["tg_id"],
                        result.photo,
                        caption=result.user_message,
                        reply_markup=back_to_main_kb(),
                    )
                else:
                    await send_message(order["tg_id"], result.user_message)
            except Exception as e:
                logger.exception("Failed to notify user after webhook: {}", e)

    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.WEBHOOK_HOST,
        port=settings.WEBHOOK_PORT,
        reload=False,
    )
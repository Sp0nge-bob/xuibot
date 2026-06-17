"""Единая обработка статусов Platega (webhook, check_pay, симулятор)."""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from aiogram.types import BufferedInputFile
from loguru import logger

from db import database as db
from services.fulfillment import fulfill_paid_order


@dataclass
class PaymentProcessResult:
    handled: bool
    user_message: Optional[str] = None
    photo: Optional[BufferedInputFile] = None
    already_paid: bool = False
    amount_mismatch: bool = False


def _amounts_match(order_amount: int, callback_amount: Any, tolerance: float = 0.01) -> bool:
    if callback_amount is None:
        return True
    try:
        return abs(float(order_amount) - float(callback_amount)) <= tolerance
    except (TypeError, ValueError):
        return False


async def handle_platega_status(
    tx_id: str,
    status: str,
    *,
    source: str = "unknown",
    callback_body: Optional[Dict[str, Any]] = None,
    notify: bool = True,
) -> PaymentProcessResult:
    """
    Обрабатывает статус транзакции Platega.
    notify=False — только обновить БД, без текста для пользователя (webhook шлёт сам).
    """
    status = (status or "").upper()
    order = await db.get_order_by_platega_tx(tx_id)
    if not order:
        logger.warning("Payment [{}]: order not found for tx {}", source, tx_id)
        return PaymentProcessResult(handled=False)

    if callback_body:
        cb_amount = callback_body.get("amount")
        cb_currency = callback_body.get("currency")
        if cb_amount is not None and not _amounts_match(order["amount"], cb_amount):
            logger.error(
                "Payment [{}]: amount mismatch tx={} order={} callback={}",
                source, tx_id, order["amount"], cb_amount,
            )
            return PaymentProcessResult(
                handled=False,
                amount_mismatch=True,
                user_message="⚠️ Сумма в callback не совпадает с заказом. Обратитесь в поддержку.",
            )
        if cb_currency and cb_currency.upper() != "RUB":
            logger.warning(
                "Payment [{}]: unexpected currency {} for tx {}",
                source, cb_currency, tx_id,
            )

    if order["status"] == "paid":
        if status == "CONFIRMED":
            return PaymentProcessResult(handled=True, already_paid=True)
        if status in ("CANCELED", "CHARGEBACKED", "FAILED"):
            await db.update_order_status(tx_id, "failed")
            msg = "❌ Платёж отменён или возвращён." if notify else None
            return PaymentProcessResult(handled=True, user_message=msg)
        return PaymentProcessResult(handled=True, already_paid=True)

    if status == "CONFIRMED":
        if not await db.mark_order_paid_if_pending(tx_id):
            return PaymentProcessResult(handled=True, already_paid=True)
        try:
            fresh_order = await db.get_order_by_platega_tx(tx_id) or order
            text, photo = await fulfill_paid_order(fresh_order)
            if notify:
                return PaymentProcessResult(handled=True, user_message=text, photo=photo)
            return PaymentProcessResult(handled=True)
        except Exception as e:
            logger.exception("Fulfillment failed [{}] tx={}: {}", source, tx_id, e)
            msg = (
                "✅ Оплата получена, но выдача ключа не удалась. Напишите в поддержку."
                if notify else None
            )
            return PaymentProcessResult(handled=True, user_message=msg)

    if status in ("CANCELED", "CHARGEBACKED", "FAILED"):
        await db.update_order_status(tx_id, "failed")
        msg = "❌ Платёж отменён или не прошёл." if notify else None
        return PaymentProcessResult(handled=True, user_message=msg)

    if status == "PENDING":
        msg = "⏳ Оплата ещё не поступила. Попробуйте через минуту." if notify else None
        return PaymentProcessResult(handled=True, user_message=msg)

    logger.info("Payment [{}]: unhandled status {} for tx {}", source, status, tx_id)
    return PaymentProcessResult(handled=False)
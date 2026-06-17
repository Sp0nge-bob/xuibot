"""Единая обработка статусов Platega (webhook, check_pay, симулятор)."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from db import database as db
from db import tickets as tickets_db
from services.fulfillment import fulfill_paid_order
from services.payment_text import payment_failed_user_text, refund_chargeback_user_text


@dataclass
class PaymentProcessResult:
    handled: bool
    user_message: Optional[str] = None
    photo: Optional[BufferedInputFile] = None
    setup_text: Optional[str] = None
    setup_photos: List[FSInputFile] = field(default_factory=list)
    already_paid: bool = False
    amount_mismatch: bool = False


# Platega может прислать в callback сумму с комиссией сверх цены заказа (1 ₽ → 1.13 ₽).
_MAX_COMMISSION_RATE = 0.25


def _callback_amount_acceptable(
    order_amount: int,
    callback_amount: Any,
    *,
    tolerance: float = 0.01,
) -> bool:
    if callback_amount is None:
        return True
    try:
        order = float(order_amount)
        callback = float(callback_amount)
    except (TypeError, ValueError):
        return False

    if abs(order - callback) <= tolerance:
        return True

    # Комиссия сверху: callback >= order и не больше разумного потолка.
    max_allowed = order * (1 + _MAX_COMMISSION_RATE) + tolerance
    return order - tolerance <= callback <= max_allowed


async def _chargeback_user_message(order: Dict[str, Any]) -> str:
    ticket = await tickets_db.get_refund_ticket_for_order(order["id"])
    ticket_id = ticket["id"] if ticket else None
    return refund_chargeback_user_text(order, ticket_id=ticket_id)


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
        if cb_amount is not None and not _callback_amount_acceptable(order["amount"], cb_amount):
            logger.error(
                "Payment [{}]: amount mismatch tx={} order={} callback={}",
                source, tx_id, order["amount"], cb_amount,
            )
            return PaymentProcessResult(
                handled=False,
                amount_mismatch=True,
                user_message=payment_failed_user_text(
                    order,
                    title=(
                        "⚠️ <b>Оплата не подтверждена</b>\n"
                        "<i>Сумма в callback не совпадает с заказом. Обратитесь в поддержку.</i>"
                    ),
                ),
            )
        if cb_amount is not None:
            try:
                order_amt = float(order["amount"])
                cb_amt = float(cb_amount)
                if cb_amt > order_amt + 0.01:
                    logger.info(
                        "Payment [{}]: Platega commission tx={} order={} callback={}",
                        source, tx_id, order["amount"], cb_amount,
                    )
            except (TypeError, ValueError):
                pass
        if cb_currency and cb_currency.upper() != "RUB":
            logger.warning(
                "Payment [{}]: unexpected currency {} for tx {}",
                source, cb_currency, tx_id,
            )

    if order["status"] == "paid":
        if status == "CONFIRMED":
            return PaymentProcessResult(handled=True, already_paid=True)
        if status == "CHARGEBACKED":
            await db.update_order_status(tx_id, "failed")
            msg = await _chargeback_user_message(order) if notify else None
            return PaymentProcessResult(handled=True, user_message=msg)
        if status in ("CANCELED", "FAILED"):
            await db.update_order_status(tx_id, "failed")
            msg = payment_failed_user_text(order, status=status) if notify else None
            return PaymentProcessResult(handled=True, user_message=msg)
        return PaymentProcessResult(handled=True, already_paid=True)

    if status == "CONFIRMED":
        if not await db.mark_order_paid_if_pending(tx_id):
            return PaymentProcessResult(handled=True, already_paid=True)
        try:
            fresh_order = await db.get_order_by_platega_tx(tx_id) or order
            fulfillment = await fulfill_paid_order(fresh_order)
            if notify:
                return PaymentProcessResult(
                    handled=True,
                    user_message=fulfillment.text,
                    photo=fulfillment.photo,
                    setup_text=fulfillment.setup_text,
                    setup_photos=fulfillment.setup_photos,
                )
            return PaymentProcessResult(handled=True)
        except Exception as e:
            logger.exception("Fulfillment failed [{}] tx={}: {}", source, tx_id, e)
            msg = (
                "✅ Оплата получена, но выдача ключа не удалась. Напишите в поддержку."
                if notify else None
            )
            return PaymentProcessResult(handled=True, user_message=msg)

    if status == "CHARGEBACKED":
        await db.update_order_status(tx_id, "failed")
        msg = await _chargeback_user_message(order) if notify else None
        return PaymentProcessResult(handled=True, user_message=msg)

    if status in ("CANCELED", "FAILED"):
        await db.update_order_status(tx_id, "failed")
        msg = payment_failed_user_text(order, status=status) if notify else None
        return PaymentProcessResult(handled=True, user_message=msg)

    if status == "PENDING":
        msg = "⏳ Оплата ещё не поступила. Попробуйте через минуту." if notify else None
        return PaymentProcessResult(handled=True, user_message=msg)

    logger.info("Payment [{}]: unhandled status {} for tx {}", source, status, tx_id)
    return PaymentProcessResult(handled=False)
"""Скрипт для повторной выдачи (re-fulfillment) оплаченного заказа, завершившегося сбоем."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from config.settings import settings
import db.database as db
from services.fulfillment import fulfill_paid_order
from aiogram import Bot


async def refulfill(tx_id: str | None = None, order_id: int | None = None) -> None:
    await db.init_db()
    order = None
    if tx_id:
        order = await db.get_order_by_platega_tx(tx_id)
    elif order_id:
        order = await db.get_order_by_id(order_id)

    if not order:
        logger.error("Заказ не найден (tx={}, order_id={})", tx_id, order_id)
        return

    logger.info(
        "Найден заказ #{}: tg_id={}, plan_id={}, status={}, sub_id={}",
        order.get("id"),
        order.get("tg_id"),
        order.get("plan_id"),
        order.get("status"),
        order.get("subscription_id"),
    )

    if order.get("subscription_id"):
        logger.warning(
            "У заказа #{} уже привязана подписка id={}! Повторная выдача может продлить или перезаписать клиента.",
            order.get("id"),
            order.get("subscription_id"),
        )

    logger.info("Запуск fulfill_paid_order...")
    res = await fulfill_paid_order(order)
    logger.success("Fulfillment выполнен! sub_id={}, subscription_id={}", res.sub_id, res.subscription_id)

    # Отправляем сообщение пользователю в Telegram
    tg_id = order.get("tg_id")
    if tg_id and settings.BOT_TOKEN and res.text:
        bot = Bot(token=settings.BOT_TOKEN)
        try:
            await bot.send_message(tg_id, res.text, parse_mode="HTML")
            if res.photo:
                try:
                    await bot.send_photo(tg_id, res.photo)
                except Exception as e:
                    logger.warning("Не удалось отправить фото: {}", e)
            if res.link_message:
                await bot.send_message(tg_id, res.link_message, parse_mode="HTML")
            if res.setup_text:
                await bot.send_message(tg_id, res.setup_text, parse_mode="HTML")
            logger.success("Уведомление и ключ успешно отправлены клиенту tg_id={}", tg_id)
        except Exception as e:
            logger.error("Не удалось отправить сообщение клиенту {}: {}", tg_id, e)
        finally:
            await bot.session.close()


def main():
    parser = argparse.ArgumentParser(description="Повторная выдача подписки по оплаченному заказу")
    parser.add_argument("--tx", type=str, help="Platega transaction ID (UUID)")
    parser.add_argument("--order-id", type=int, help="ID заказа в базе данных")
    args = parser.parse_args()

    if not args.tx and not args.order_id:
        parser.error("Необходимо указать --tx <UUID> или --order-id <ID>")

    asyncio.run(refulfill(tx_id=args.tx, order_id=args.order_id))


if __name__ == "__main__":
    main()

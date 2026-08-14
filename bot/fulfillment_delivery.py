"""Доставка сообщений после успешной оплаты (QR + инструкция Happ)."""
import time
from typing import List, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile
from loguru import logger

from bot.photo_delivery import send_photos_with_text
from bot.ui_helpers import prepare_user_text


async def deliver_fulfillment(
    bot: Bot,
    chat_id: int,
    *,
    text: str,
    photo: Optional[BufferedInputFile] = None,
    link_message: Optional[str] = None,
    setup_text: Optional[str] = None,
    setup_photos: Optional[List[FSInputFile]] = None,
    reply_markup=None,
) -> None:
    """
    Сначала текст (мгновенно), потом QR/ссылка.

    Раньше success-текст уходил caption'ом к send_photo — клиент ждал
    загрузку картинки в Telegram API (часто несколько секунд после панели).
    """
    main_text = await prepare_user_text(text, chat_id)
    t0 = time.monotonic()

    # Клавиатура: на тексте, если нет отдельной ссылки; иначе — на сообщении со ссылкой
    text_markup = None if link_message else reply_markup
    await bot.send_message(
        chat_id,
        main_text,
        reply_markup=text_markup,
        parse_mode="HTML",
    )
    logger.info(
        "fulfillment text sent chat_id={} in {:.2f}s",
        chat_id,
        time.monotonic() - t0,
    )

    if photo:
        t_photo = time.monotonic()
        try:
            await bot.send_photo(
                chat_id,
                photo,
                caption="📱 <b>QR-код подписки</b>",
                parse_mode="HTML",
            )
            logger.info(
                "fulfillment QR sent chat_id={} in {:.2f}s",
                chat_id,
                time.monotonic() - t_photo,
            )
        except Exception:
            logger.exception(
                "fulfillment QR failed chat_id={} after {:.2f}s",
                chat_id,
                time.monotonic() - t_photo,
            )

    if link_message:
        t_link = time.monotonic()
        await bot.send_message(
            chat_id,
            await prepare_user_text(link_message, chat_id),
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        logger.info(
            "fulfillment link sent chat_id={} in {:.2f}s",
            chat_id,
            time.monotonic() - t_link,
        )

    if setup_text or setup_photos:
        await send_photos_with_text(
            bot,
            chat_id,
            setup_text,
            setup_photos or [],
            parse_mode="HTML",
            user_id=chat_id,
        )

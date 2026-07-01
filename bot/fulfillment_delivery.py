"""Доставка сообщений после успешной оплаты (QR + инструкция Happ)."""
from typing import List, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile

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
    main_text = await prepare_user_text(text, chat_id)
    if photo:
        await bot.send_photo(
            chat_id,
            photo,
            caption=main_text,
            parse_mode="HTML",
            reply_markup=reply_markup if not link_message else None,
        )
    else:
        await bot.send_message(
            chat_id, main_text, reply_markup=reply_markup, parse_mode="HTML",
        )

    if link_message:
        await bot.send_message(
            chat_id,
            await prepare_user_text(link_message, chat_id),
            reply_markup=reply_markup,
            parse_mode="HTML",
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
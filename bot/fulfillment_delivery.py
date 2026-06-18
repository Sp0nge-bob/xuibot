"""Доставка сообщений после успешной оплаты (QR + инструкция Happ)."""
from typing import List, Optional

from aiogram import Bot
from aiogram.types import BufferedInputFile, FSInputFile, InputMediaPhoto


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
    if photo:
        await bot.send_photo(
            chat_id,
            photo,
            caption=text,
            reply_markup=reply_markup if not link_message else None,
        )
    else:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)

    if link_message:
        await bot.send_message(
            chat_id,
            link_message,
            reply_markup=reply_markup,
        )

    if not setup_text and not setup_photos:
        return

    photos = setup_photos or []
    if photos:
        if len(photos) == 1:
            await bot.send_photo(chat_id, photos[0], caption=setup_text)
        else:
            media = [
                InputMediaPhoto(
                    media=photos[0],
                    caption=setup_text,
                ),
                *[InputMediaPhoto(media=p) for p in photos[1:]],
            ]
            await bot.send_media_group(chat_id, media)
    elif setup_text:
        await bot.send_message(chat_id, setup_text)
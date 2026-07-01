"""Текст + фото: sendMediaGroup с caption только на первом элементе."""
from __future__ import annotations

from typing import Union

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto
from loguru import logger

from bot.ui_helpers import clamp_telegram_text

PhotoMedia = Union[str, FSInputFile]
CAPTION_LIMIT = 1024
MEDIA_GROUP_MAX = 10


def build_media_group(
    photos: list[PhotoMedia],
    *,
    caption: str | None = None,
    parse_mode: str = "HTML",
) -> list[InputMediaPhoto]:
    batch = photos[:MEDIA_GROUP_MAX]
    if not batch:
        return []
    first = InputMediaPhoto(
        media=batch[0],
        caption=caption,
        parse_mode=parse_mode if caption else None,
    )
    return [first, *[InputMediaPhoto(media=p) for p in batch[1:]]]


async def _attach_reply_markup(
    bot: Bot,
    chat_id: int,
    message_id: int,
    reply_markup,
) -> None:
    if not reply_markup:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.debug("Не удалось повесить кнопки на фото {}: {}", message_id, e)


async def send_photos_with_text(
    bot: Bot,
    chat_id: int,
    text: str | None,
    photos: list[PhotoMedia],
    *,
    reply_markup=None,
    parse_mode: str = "HTML",
) -> list[int]:
    """
    Доставка текста с фото по правилам Telegram.

    - Без фото: одно текстовое сообщение (редактируется при навигации).
    - 1 фото: send_photo с caption (до 1024 симв.).
    - 2+ фото: send_media_group, caption только у первого; кнопки на первом сообщении.

    Возвращает message_id фото-сообщений для удаления при выходе из просмотра.
    Для чистого текста возвращает [] — сообщение редактируется на месте.
    """
    body = (text or "").strip()
    caption = clamp_telegram_text(body, limit=CAPTION_LIMIT) if body else None

    if not photos:
        if not body:
            return []
        await bot.send_message(
            chat_id,
            clamp_telegram_text(body),
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return []

    batch = photos[:MEDIA_GROUP_MAX]

    if len(batch) == 1:
        msg = await bot.send_photo(
            chat_id,
            batch[0],
            caption=caption,
            parse_mode=parse_mode if caption else None,
            reply_markup=reply_markup,
        )
        return [msg.message_id]

    media = build_media_group(batch, caption=caption, parse_mode=parse_mode)
    album_messages = await bot.send_media_group(chat_id, media)
    if album_messages:
        await _attach_reply_markup(
            bot, chat_id, album_messages[0].message_id, reply_markup,
        )
    return [msg.message_id for msg in album_messages]
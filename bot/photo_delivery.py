"""Текст + фото: sendMediaGroup с caption только на первом элементе."""
from __future__ import annotations

from typing import Union

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto

from bot.ui_helpers import clamp_telegram_text

PhotoMedia = Union[str, FSInputFile]
CAPTION_LIMIT = 1024
MEDIA_GROUP_MAX = 10
MEDIA_GROUP_ACTION_HINT = "👇 Выберите действие:"


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

    - Без фото: одно текстовое сообщение.
    - 1 фото: send_photo с caption (до 1024 симв.) и кнопками.
    - 2+ фото: send_media_group (caption только у первого), затем сообщение с кнопками
      (sendMediaGroup не поддерживает reply_markup).

    Возвращает message_id всех отправленных сообщений просмотра.
    """
    body = (text or "").strip()
    caption = clamp_telegram_text(body, limit=CAPTION_LIMIT) if body else None

    if not photos:
        if not body:
            return []
        msg = await bot.send_message(
            chat_id,
            clamp_telegram_text(body),
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return [msg.message_id]

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
    message_ids = [msg.message_id for msg in album_messages]

    if reply_markup:
        nav = await bot.send_message(
            chat_id,
            MEDIA_GROUP_ACTION_HINT,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        message_ids.append(nav.message_id)

    return message_ids
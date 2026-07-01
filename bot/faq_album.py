"""ID фото-сообщений FAQ для удаления при выходе из статьи (альбом не редактируется в меню)."""
from __future__ import annotations

from aiogram import Bot
from loguru import logger

_album_message_ids: dict[int, list[int]] = {}


def set_faq_album_message_ids(chat_id: int, message_ids: list[int]) -> None:
    _album_message_ids[chat_id] = list(message_ids)


async def clear_faq_album(bot: Bot, chat_id: int) -> None:
    ids = _album_message_ids.pop(chat_id, [])
    for message_id in ids:
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as e:
            logger.debug("FAQ album delete {}:{} — {}", chat_id, message_id, e)
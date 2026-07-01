"""Сообщения открытой FAQ-статьи — удаляются целиком при выходе."""
from __future__ import annotations

from aiogram import Bot
from loguru import logger

_view_message_ids: dict[int, list[int]] = {}


def set_faq_view_message_ids(chat_id: int, message_ids: list[int]) -> None:
    _view_message_ids[chat_id] = list(message_ids)


async def dismiss_faq_view(bot: Bot, chat_id: int) -> bool:
    """Удалить все сообщения просмотра статьи одним запросом. True — что-то было удалено."""
    ids = _view_message_ids.pop(chat_id, [])
    if not ids:
        return False
    try:
        await bot.delete_messages(chat_id, ids)
    except Exception as e:
        logger.debug("FAQ view batch delete failed ({}), fallback per message", e)
        for message_id in ids:
            try:
                await bot.delete_message(chat_id, message_id)
            except Exception as inner:
                logger.debug("FAQ view delete {}:{} — {}", chat_id, message_id, inner)
    return True
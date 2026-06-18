"""Отправка FAQ-статьи клиенту (текст + до 10 фото)."""
from __future__ import annotations

import html
from typing import Any, Union

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto

from bot.telegram_html import safe_html_fragment
from bot.ui_helpers import clamp_telegram_text
from services.fulfillment import load_happ_setup_photos

_PhotoMedia = Union[str, FSInputFile]


def _build_faq_header(article: dict[str, Any]) -> str:
    title = html.escape((article.get("title") or "").strip())
    body_raw = (article.get("body") or "").strip()
    body = safe_html_fragment(body_raw) if body_raw else ""
    header = f"<b>{title}</b>"
    if body:
        header = f"{header}\n\n{body}"
    return clamp_telegram_text(header)


async def _send_faq_header_and_photos(
    bot: Bot,
    chat_id: int,
    header: str,
    photos: list[_PhotoMedia],
    *,
    reply_markup=None,
) -> None:
    """Текст статьи + фото. При нескольких фото кнопки — под текстом, без «⬆️»."""
    if not photos:
        await bot.send_message(chat_id, header, reply_markup=reply_markup)
        return

    if len(photos) == 1:
        if len(header) <= 1024:
            await bot.send_photo(
                chat_id,
                photos[0],
                caption=header,
                reply_markup=reply_markup,
            )
            return
        await bot.send_message(chat_id, header, reply_markup=reply_markup)
        await bot.send_photo(chat_id, photos[0])
        return

    await bot.send_message(chat_id, header, reply_markup=reply_markup)
    media = [InputMediaPhoto(media=photo) for photo in photos[:10]]
    await bot.send_media_group(chat_id, media)


async def send_faq_article(
    bot: Bot,
    chat_id: int,
    article: dict[str, Any],
    photos: list[dict[str, Any]],
    *,
    reply_markup=None,
) -> None:
    header = _build_faq_header(article)
    file_ids = [p["file_id"] for p in photos if p.get("file_id")][:10]
    await _send_faq_header_and_photos(
        bot, chat_id, header, file_ids, reply_markup=reply_markup,
    )


async def send_activation_setup_faq(
    bot: Bot,
    chat_id: int,
    article: dict[str, Any],
    *,
    reply_markup=None,
) -> None:
    """Встроенная FAQ-статья — тот же текст и скриншоты, что после оплаты/пробного."""
    header = _build_faq_header(article)
    photos: list[FSInputFile] = load_happ_setup_photos()
    await _send_faq_header_and_photos(
        bot, chat_id, header, photos, reply_markup=reply_markup,
    )
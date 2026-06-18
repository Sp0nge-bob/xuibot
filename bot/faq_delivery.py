"""Отправка FAQ-статьи клиенту (текст + до 10 фото)."""
from __future__ import annotations

import html
from typing import Any, Optional

from aiogram import Bot
from aiogram.types import InputMediaPhoto

from bot.telegram_html import safe_html_fragment
from bot.ui_helpers import clamp_telegram_text


async def send_faq_article(
    bot: Bot,
    chat_id: int,
    article: dict[str, Any],
    photos: list[dict[str, Any]],
    *,
    reply_markup=None,
) -> None:
    title = html.escape((article.get("title") or "").strip())
    body_raw = (article.get("body") or "").strip()
    body = safe_html_fragment(body_raw) if body_raw else ""
    header = f"<b>{title}</b>"
    if body:
        header = f"{header}\n\n{body}"

    file_ids = [p["file_id"] for p in photos if p.get("file_id")][:10]

    if not file_ids:
        await bot.send_message(
            chat_id,
            clamp_telegram_text(header),
            reply_markup=reply_markup,
        )
        return

    if len(file_ids) == 1:
        if len(header) <= 1024:
            await bot.send_photo(
                chat_id,
                file_ids[0],
                caption=header,
                reply_markup=reply_markup,
            )
            return
        await bot.send_message(chat_id, clamp_telegram_text(header))
        await bot.send_photo(chat_id, file_ids[0], reply_markup=reply_markup)
        return

    if len(header) > 1024:
        await bot.send_message(chat_id, clamp_telegram_text(header))
        media = [InputMediaPhoto(media=fid) for fid in file_ids]
        await bot.send_media_group(chat_id, media)
        if reply_markup:
            await bot.send_message(chat_id, "⬆️", reply_markup=reply_markup)
        return

    media = [InputMediaPhoto(media=file_ids[0], caption=header)]
    media.extend(InputMediaPhoto(media=fid) for fid in file_ids[1:])
    await bot.send_media_group(chat_id, media)
    if reply_markup:
        await bot.send_message(chat_id, "⬆️", reply_markup=reply_markup)
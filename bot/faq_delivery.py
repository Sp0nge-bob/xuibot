"""Отправка FAQ-статьи клиенту (текст + до 10 фото)."""
from __future__ import annotations

import html
from typing import Any

from aiogram import Bot

from bot.photo_delivery import send_photos_with_text
from bot.telegram_html import safe_html_fragment
from bot.ui_helpers import clamp_telegram_text
from services.fulfillment import load_happ_setup_photos


def _build_faq_header(article: dict[str, Any]) -> str:
    title = html.escape((article.get("title") or "").strip())
    body_raw = (article.get("body") or "").strip()
    body = safe_html_fragment(body_raw) if body_raw else ""
    header = f"<b>{title}</b>"
    if body:
        header = f"{header}\n\n{body}"
    return clamp_telegram_text(header)


async def send_faq_article(
    bot: Bot,
    chat_id: int,
    article: dict[str, Any],
    photos: list[dict[str, Any]],
    *,
    reply_markup=None,
) -> list[int]:
    header = _build_faq_header(article)
    file_ids = [p["file_id"] for p in photos if p.get("file_id")]
    return await send_photos_with_text(
        bot, chat_id, header, file_ids, reply_markup=reply_markup, user_id=chat_id,
    )


async def send_activation_setup_faq(
    bot: Bot,
    chat_id: int,
    article: dict[str, Any] | None = None,
    *,
    reply_markup=None,
    client: str | None = None,
) -> list[int]:
    """Встроенная FAQ-статья подключения: выбор приложения, Happ (со скриншотами) или INCY."""
    from services.fulfillment_text import (
        activation_setup_text,
        happ_setup_text,
        incy_setup_text,
    )

    if client == "happ":
        return await send_photos_with_text(
            bot,
            chat_id,
            happ_setup_text(),
            load_happ_setup_photos(),
            reply_markup=reply_markup,
            user_id=chat_id,
        )
    if client == "incy":
        return await send_photos_with_text(
            bot,
            chat_id,
            incy_setup_text(),
            [],
            reply_markup=reply_markup,
            user_id=chat_id,
        )
    header = _build_faq_header(article) if article else activation_setup_text()
    return await send_photos_with_text(
        bot,
        chat_id,
        header,
        [],
        reply_markup=reply_markup,
        user_id=chat_id,
    )
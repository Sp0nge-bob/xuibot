"""Relay-переписка по тикетам (все типы сообщений Telegram)."""
from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from loguru import logger

from config.settings import settings
from db import tickets as tickets_db

# Активные relay-сессии: tg_id -> ticket_id
_active_sessions: dict[int, int] = {}

_CAPTION_TYPES = frozenset({"photo", "video", "document", "audio", "animation"})

_CONTENT_PREVIEW = {
    "photo": "📷 Фото",
    "video": "🎬 Видео",
    "voice": "🎤 Голосовое",
    "video_note": "📹 Кружок",
    "sticker": "🙂 Стикер",
    "animation": "🎞 GIF",
    "document": "📎 Документ",
    "audio": "🎵 Аудио",
    "contact": "👤 Контакт",
    "location": "📍 Локация",
}


def set_active_session(tg_id: int, ticket_id: int) -> int | None:
    """Войти в сессию. Возвращает предыдущий ticket_id, если был."""
    prev = _active_sessions.get(tg_id)
    _active_sessions[tg_id] = ticket_id
    return prev


def clear_active_session(tg_id: int, *, ticket_id: int | None = None) -> None:
    if ticket_id is None:
        _active_sessions.pop(tg_id, None)
        return
    if _active_sessions.get(tg_id) == ticket_id:
        _active_sessions.pop(tg_id, None)


def get_active_session(tg_id: int) -> int | None:
    return _active_sessions.get(tg_id)


def user_label(
    *,
    username: str | None,
    first_name: str | None,
    tg_id: int,
    is_admin: bool = False,
) -> str:
    if is_admin:
        return "Администратор"
    if username:
        return f"@{username}"
    if first_name:
        return first_name
    return str(tg_id)


def ticket_relay_prefix(ticket_id: int, sender_label: str, category: str) -> str:
    cat = tickets_db.category_label(category)
    return f"🎫 Тикет #{ticket_id} · {sender_label} · {cat}"


def extract_message_content(message: Message) -> tuple[str, str | None, str | None]:
    """content_type, body (text/caption), file_id."""
    if message.text:
        return "text", message.text, None
    if message.photo:
        return "photo", message.caption, message.photo[-1].file_id
    if message.video:
        return "video", message.caption, message.video.file_id
    if message.voice:
        return "voice", None, message.voice.file_id
    if message.video_note:
        return "video_note", None, message.video_note.file_id
    if message.sticker:
        return "sticker", None, message.sticker.file_id
    if message.animation:
        return "animation", message.caption, message.animation.file_id
    if message.document:
        return "document", message.caption, message.document.file_id
    if message.audio:
        return "audio", message.caption, message.audio.file_id
    if message.contact:
        c = message.contact
        return "contact", f"{c.first_name or ''} {c.phone_number}".strip(), None
    if message.location:
        loc = message.location
        return "location", f"{loc.latitude}, {loc.longitude}", None
    return "text", message.caption or "(неподдерживаемый тип)", None


def message_preview(content_type: str, body: str | None) -> str:
    if content_type == "text" and body:
        text = body.strip()
        return text[:200] + ("..." if len(text) > 200 else "")
    return _CONTENT_PREVIEW.get(content_type, "💬 Сообщение")


def _admin_notification_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📋 Открыть тикет",
                callback_data=f"adm:ticket:{ticket_id}",
            ),
            InlineKeyboardButton(
                text="💬 Начать переписку",
                callback_data=f"adm:ticket:session:{ticket_id}",
            ),
        ],
    ])


async def _copy_with_prefix(
    bot: Bot,
    *,
    target_chat_id: int,
    message: Message,
    prefix: str,
) -> None:
    content_type, body, _ = extract_message_content(message)
    supports_caption = content_type in _CAPTION_TYPES

    if content_type == "text":
        await bot.send_message(target_chat_id, f"{prefix}\n\n{body or ''}")
        return

    if supports_caption:
        new_caption = f"{prefix}\n\n{body}" if body else prefix
        if len(new_caption) > 1024:
            await bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
            await bot.send_message(target_chat_id, prefix)
            return
        await bot.copy_message(
            chat_id=target_chat_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            caption=new_caption,
        )
        return

    await bot.copy_message(
        chat_id=target_chat_id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await bot.send_message(target_chat_id, prefix)


async def _notify_admins_card(
    bot: Bot,
    *,
    ticket: dict[str, Any],
    preview: str,
    sender_label: str,
) -> None:
    order_line = ""
    if ticket.get("order_id"):
        tx = ticket.get("platega_tx_id") or "—"
        order_line = (
            f"\n🧾 Заказ: <code>#{ticket['order_id']}</code>"
            f"\n🆔 TX: <code>{tx}</code>"
        )
    text = (
        f"💬 <b>Новое в тикете #{ticket['id']}</b>\n"
        f"👤 {sender_label} (<code>{ticket['tg_id']}</code>)\n"
        f"📁 {tickets_db.category_label(ticket['category'])}{order_line}\n"
        "━━━━━━━━━━━━━━━━\n"
        f"{preview}"
    )
    kb = _admin_notification_kb(ticket["id"])
    for admin_id in settings.BOT_ADMINS:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            logger.debug("Failed to notify admin {} about ticket {}", admin_id, ticket["id"])


async def relay_ticket_message(
    message: Message,
    *,
    ticket: dict[str, Any],
    is_admin: bool,
    bot: Bot,
) -> bool:
    """Переслать сообщение второй стороне. False если тикет закрыт."""
    if ticket.get("status") != tickets_db.STATUS_OPEN:
        return False

    content_type, body, file_id = extract_message_content(message)
    await tickets_db.add_ticket_message(
        ticket_id=ticket["id"],
        sender_tg_id=message.from_user.id,
        is_admin=is_admin,
        content_type=content_type,
        body=body,
        file_id=file_id,
    )

    sender = user_label(
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        tg_id=message.from_user.id,
        is_admin=is_admin,
    )
    prefix = ticket_relay_prefix(ticket["id"], sender, ticket["category"])
    preview = message_preview(content_type, body)

    if is_admin:
        try:
            user_session = get_active_session(ticket["tg_id"])
            if user_session == ticket["id"]:
                await _copy_with_prefix(
                    bot,
                    target_chat_id=ticket["tg_id"],
                    message=message,
                    prefix=prefix,
                )
            else:
                await bot.send_message(
                    ticket["tg_id"],
                    f"💬 <b>Ответ по тикету #{ticket['id']}</b>\n"
                    f"🛠 <b>Администратор</b>\n\n{preview}",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="💬 Начать переписку",
                            callback_data=f"ticket_session:{ticket['id']}",
                        ),
                    ]]),
                )
        except Exception:
            logger.exception("Failed to deliver admin message for ticket {}", ticket["id"])
    else:
        relayed_live = False
        for admin_id in settings.BOT_ADMINS:
            try:
                if get_active_session(admin_id) == ticket["id"]:
                    await _copy_with_prefix(
                        bot,
                        target_chat_id=admin_id,
                        message=message,
                        prefix=prefix,
                    )
                    relayed_live = True
            except Exception:
                logger.debug("Failed relay to admin {}", admin_id)
        if not relayed_live:
            await _notify_admins_card(
                bot,
                ticket=ticket,
                preview=preview,
                sender_label=sender,
            )

    return True
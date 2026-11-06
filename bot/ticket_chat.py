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
    import html
    if is_admin:
        return "Администратор"
    if username:
        return f"@{html.escape(username)}"
    if first_name:
        return html.escape(first_name)
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
    import html
    if content_type == "text" and body:
        text = body.strip()
        raw_preview = text[:200] + ("..." if len(text) > 200 else "")
        return html.escape(raw_preview)
    return _CONTENT_PREVIEW.get(content_type, "💬 Сообщение")


def format_ticket_message_time(created_at: str | None) -> str:
    """Форматирует timestamp в читаемое время (ДД.ММ ЧЧ:ММ)."""
    if not created_at:
        return "—"
    s = str(created_at).replace("T", " ")
    if len(s) >= 16 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}.{s[5:7]} {s[11:16]}"
    return s[:16]


def format_ticket_message_snippet(
    msg: dict[str, Any],
    *,
    viewer_is_admin: bool = True,
    ticket_user_label: str = "",
) -> str:
    """Краткое превью сообщения для карточки тикета."""
    import html
    time_str = format_ticket_message_time(msg.get("created_at"))
    if msg.get("is_admin"):
        author = "🛠 Администратор"
    else:
        if viewer_is_admin and ticket_user_label:
            author = f"👤 {ticket_user_label}"
        elif viewer_is_admin:
            author = "👤 Клиент"
        else:
            author = "👤 Вы"

    content_type = msg.get("content_type", "text")
    body = (msg.get("body") or "").strip()

    if content_type == "text":
        body_preview = html.escape(body[:140] + ("..." if len(body) > 140 else ""))
        text_line = body_preview if body_preview else "<i>(текст)</i>"
    else:
        type_label = _CONTENT_PREVIEW.get(content_type, "📎 Вложение")
        if body:
            body_preview = html.escape(body[:100] + ("..." if len(body) > 100 else ""))
            text_line = f"{type_label}: <i>{body_preview}</i>"
        else:
            text_line = f"<i>{type_label}</i>"
    return f"[{time_str}] {author}:\n{text_line}"


def render_ticket_history_text(
    ticket: dict[str, Any],
    messages: list[dict[str, Any]],
    *,
    page: int = 1,
    total_pages: int = 1,
    total_count: int = 0,
    viewer_is_admin: bool = True,
    ticket_user_label: str = "",
) -> str:
    """Полный экран истории сообщений с постраничной разбивкой."""
    import html
    ticket_id = ticket["id"]
    cat = tickets_db.category_label(ticket.get("category", "other"))
    status = "открыт" if ticket.get("status") == tickets_db.STATUS_OPEN else "закрыт"

    header_lines = [
        f"📜 <b>История переписки: Тикет #{ticket_id}</b>",
        f"📁 Категория: <b>{cat}</b> · 📌 Статус: <b>{status}</b>",
    ]
    if viewer_is_admin and ticket_user_label:
        header_lines.append(f"👤 Пользователь: {ticket_user_label} (<code>{ticket.get('tg_id')}</code>)")

    if total_count == 0 or not messages:
        header_lines += [
            "━━━━━━━━━━━━━━━━",
            "<i>В этом тикете пока нет сообщений.</i>",
        ]
        return "\n".join(header_lines)

    header_lines += [
        f"📄 Страница <b>{page} из {total_pages}</b> (сообщений: <b>{total_count}</b>)",
        "━━━━━━━━━━━━━━━━",
        "",
    ]

    msg_blocks: list[str] = []
    for m in messages:
        time_str = format_ticket_message_time(m.get("created_at"))
        if m.get("is_admin"):
            author = "🛠 <b>Администратор</b>"
        else:
            if viewer_is_admin and ticket_user_label:
                author = f"👤 <b>{ticket_user_label}</b>"
            elif viewer_is_admin:
                author = "👤 <b>Клиент</b>"
            else:
                author = "👤 <b>Вы</b>"

        content_type = m.get("content_type", "text")
        body = (m.get("body") or "").strip()

        if content_type == "text":
            escaped_body = html.escape(body[:450] + ("... [обрезано]" if len(body) > 450 else ""))
            content_display = escaped_body if escaped_body else "<i>(текст)</i>"
        else:
            type_label = _CONTENT_PREVIEW.get(content_type, "📎 Вложение")
            if body:
                escaped_body = html.escape(body[:350] + ("... [обрезано]" if len(body) > 350 else ""))
                content_display = f"{type_label}: <i>{escaped_body}</i>"
            else:
                content_display = f"<i>{type_label}</i>"

        msg_blocks.append(f"[{time_str}] {author}\n{content_display}")

    return "\n".join(header_lines) + "\n\n────────────────\n\n".join(msg_blocks)


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
    import html
    content_type, body, _ = extract_message_content(message)
    supports_caption = content_type in _CAPTION_TYPES
    safe_body = html.escape(body) if body else ""

    if content_type == "text":
        await bot.send_message(target_chat_id, f"{prefix}\n\n{safe_body}")
        return

    if supports_caption:
        new_caption = f"{prefix}\n\n{safe_body}" if safe_body else prefix
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
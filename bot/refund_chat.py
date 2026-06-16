"""Переписка по запросам на возврат (админ ↔ пользователь)."""
from db import database as db
from config.settings import settings


def format_refund_chat_history(messages: list[dict], *, refund_id: int, for_admin: bool) -> str:
    header = (
        "💬 <b>Переписка по возврату</b>\n"
        f"Запрос <code>#{refund_id}</code>\n"
        "━━━━━━━━━━━━━━━━\n"
    )
    if not messages:
        body = "<i>Сообщений пока нет. Напишите первым.</i>"
        return header + "\n" + body

    lines: list[str] = []
    for msg in messages[-30:]:
        if msg["is_admin"]:
            who = "🛠 Админ"
        else:
            who = "👤 Клиент" if for_admin else "👤 Вы"
        ts = (msg.get("created_at") or "")[:16].replace("T", " ")
        text = (msg.get("body") or "").strip()
        if len(text) > 500:
            text = text[:497] + "..."
        lines.append(f"{who} <i>({ts})</i>\n{text}")

    body = "\n\n".join(lines)
    full = header + "\n" + body
    if len(full) > 3900:
        full = full[:3897] + "..."
    return full


async def store_and_deliver_refund_message(
    *,
    refund_id: int,
    sender_tg_id: int,
    is_admin: bool,
    body: str,
    bot,
) -> dict | None:
    """Сохранить сообщение и доставить второй стороне."""
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row.get("status") != "pending":
        return None

    msg_id = await db.add_refund_message(
        refund_id=refund_id,
        sender_tg_id=sender_tg_id,
        is_admin=is_admin,
        body=body,
    )

    preview = body if len(body) <= 200 else body[:197] + "..."
    if is_admin:
        try:
            await bot.send_message(
                row["tg_id"],
                f"💬 <b>Сообщение по возврату #{refund_id}</b>\n"
                f"🛠 <b>Администратор:</b>\n{preview}",
            )
        except Exception:
            pass
    else:
        label = row.get("username") or row.get("first_name") or str(row["tg_id"])
        notify_text = (
            f"💬 <b>Ответ по возврату #{refund_id}</b>\n"
            f"👤 {label} (<code>{row['tg_id']}</code>):\n{preview}"
        )
        for admin_id in settings.BOT_ADMINS:
            try:
                await bot.send_message(admin_id, notify_text)
            except Exception:
                pass

    return await db.get_refund_message_by_id(msg_id)
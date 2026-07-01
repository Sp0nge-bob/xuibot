from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from loguru import logger

from services.secondary_node_notice import get_secondary_node_notice

_TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_SAFE_LIMIT = 3900
_TELEGRAM_SAFE_LIMIT = TELEGRAM_SAFE_LIMIT


async def prepare_user_text(text: str, user_id: int | None) -> str:
    """Добавить приписку о недоступной вторичной ноде."""
    body = (text or "").strip()
    if not body:
        return text or ""
    notice = await get_secondary_node_notice()
    if not notice or notice in body:
        return text
    return f"{text}\n\n{notice}"


def clamp_telegram_text(text: str, *, limit: int = _TELEGRAM_SAFE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 24] + "\n\n… <i>(сообщение обрезано)</i>"


async def safe_cb_answer(
    cb: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    try:
        await cb.answer(text, show_alert=show_alert)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg:
            logger.debug("Просроченный callback проигнорирован: {}", cb.data)
        else:
            raise


async def user_answer(message: Message, text: str, **kwargs):
    user_id = message.from_user.id if message.from_user else None
    prepared = await prepare_user_text(text, user_id)
    return await message.answer(clamp_telegram_text(prepared), **kwargs)


async def user_cb_message_answer(cb: CallbackQuery, text: str, **kwargs):
    if not cb.message:
        return None
    user_id = cb.from_user.id if cb.from_user else None
    prepared = await prepare_user_text(text, user_id)
    return await cb.message.answer(clamp_telegram_text(prepared), **kwargs)


async def send_or_edit(
    cb: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует текст или отправляет новое сообщение (если текущее — фото/без текста)."""
    user_id = cb.from_user.id if cb.from_user else None
    text = clamp_telegram_text(await prepare_user_text(text, user_id))
    if cb.message.photo or cb.message.document or not cb.message.text:
        await cb.message.answer(text, reply_markup=reply_markup)
        return
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        if "message is too long" in msg:
            short = clamp_telegram_text(text, limit=3500)
            await cb.message.edit_text(short, reply_markup=reply_markup)
            return
        if "no text" in msg:
            await cb.message.answer(text, reply_markup=reply_markup)
        else:
            raise
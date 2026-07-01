from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from loguru import logger

_TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_SAFE_LIMIT = 3900
_TELEGRAM_SAFE_LIMIT = TELEGRAM_SAFE_LIMIT


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


async def send_or_edit(
    cb: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Редактирует текст или отправляет новое сообщение (если текущее — фото/без текста)."""
    text = clamp_telegram_text(text)
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
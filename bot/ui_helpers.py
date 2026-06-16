from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from loguru import logger


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
    if cb.message.photo or cb.message.document or not cb.message.text:
        await cb.message.answer(text, reply_markup=reply_markup)
        return
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        msg = str(e).lower()
        if "message is not modified" in msg:
            return
        if "no text" in msg:
            await cb.message.answer(text, reply_markup=reply_markup)
        else:
            raise
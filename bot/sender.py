from loguru import logger
import sys

async def send_message(chat_id: int, text: str, **kwargs):
    """Утилита для отправки сообщений из webhook / других сервисов.
    Ленивый доступ к bot инстансу чтобы избежать цикла импортов.
    """
    try:
        from .ui_helpers import clamp_telegram_text, prepare_user_text

        bot_mod = sys.modules[__package__.partition(".")[0]]
        prepared = await prepare_user_text(text, chat_id)
        await bot_mod.bot.send_message(
            chat_id, clamp_telegram_text(prepared), **kwargs,
        )
    except Exception as e:
        logger.error("Failed to send message to {}: {}", chat_id, e)

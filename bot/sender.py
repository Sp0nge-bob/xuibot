from loguru import logger
import sys

async def send_message(chat_id: int, text: str, **kwargs):
    """Утилита для отправки сообщений из webhook / других сервисов.
    Ленивый доступ к bot инстансу чтобы избежать цикла импортов.
    """
    try:
        bot_mod = sys.modules[__package__.partition(".")[0]]
        await bot_mod.bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error("Failed to send message to {}: {}", chat_id, e)

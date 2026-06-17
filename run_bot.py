"""
Прямой запуск Telegram-бота (polling).

Рекомендуется для надёжности, особенно когда используешь polling.

Запуск:
    python run_bot.py

Или через screen на VPS:
    screen -S bot
    python run_bot.py
    # Ctrl+A, D — чтобы отсоединиться

Этот способ избегает сложностей с FastAPI lifespan + asyncio.create_task
для долгоживущего polling-цикла.
"""
import asyncio

from bot import start_bot
from bot.shutdown import graceful_shutdown, install_shutdown_handlers
from db.database import init_db


async def _main() -> None:
    install_shutdown_handlers()
    await init_db()
    try:
        await start_bot()
    finally:
        await graceful_shutdown(reason="run_bot")


if __name__ == "__main__":
    print("Starting Telegram bot (polling mode)...")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
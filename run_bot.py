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

if __name__ == "__main__":
    print("Starting Telegram bot (polling mode)...")
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")

"""
Запуск Telegram-бота (polling) — отдельный процесс от webhook.

Продакшен (два процесса):
    python app.py        # FastAPI + webhook Platega
    python run_bot.py    # Telegram polling + планировщик

Локальная разработка — то же самое. Одна команда (два процесса):
    python run_all.py

Монолит в одном процессе: START_BOT_IN_WEBAPP=true в .env, затем python app.py
"""
import asyncio

from bot.shutdown import graceful_shutdown, install_shutdown_handlers
from db.database import init_db


async def _main() -> None:
    install_shutdown_handlers()
    await init_db()
    from bot import start_bot

    try:
        await start_bot()
    finally:
        await graceful_shutdown(reason="run_bot")


if __name__ == "__main__":
    print("Starting Telegram bot (polling)...")
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
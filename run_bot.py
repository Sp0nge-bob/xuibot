from config.logging_setup import init_logging

init_logging("bot")

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

from bot.shutdown import ensure_shutdown_complete, install_shutdown_handlers
from db.database import init_db


async def _main() -> None:
    from config.settings import warn_unsafe_runtime_config

    warn_unsafe_runtime_config()
    install_shutdown_handlers()
    await init_db()
    from bot import start_bot

    try:
        await start_bot()
    except RuntimeError as e:
        print(f"\n{e}")
        return
    except asyncio.CancelledError:
        pass
    finally:
        await ensure_shutdown_complete(reason="run_bot")


if __name__ == "__main__":
    print("Starting Telegram bot (polling)...")
    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nBot stopped.")
    except RuntimeError as e:
        print(f"\n{e}")
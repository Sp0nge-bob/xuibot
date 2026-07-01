"""Runtime TEST_MODE: переопределение из админки поверх .env."""
from config.settings import settings
from db import bot_settings as bot_settings_db


async def is_test_mode() -> bool:
    override = await bot_settings_db.get_test_mode_override()
    if override is None:
        return settings.TEST_MODE
    return override


async def is_test_mode_overridden() -> bool:
    return await bot_settings_db.is_test_mode_overridden()


async def set_test_mode(enabled: bool) -> None:
    await bot_settings_db.set_test_mode(enabled)


async def clear_test_mode_override() -> None:
    await bot_settings_db.clear_test_mode_override()


async def test_mode_source_label() -> str:
    if await is_test_mode_overridden():
        return "БД"
    return ".env"
"""Меню команд слева от строки ввода (кнопка ☰ → всплывающий список)."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, MenuButtonCommands
from loguru import logger

USER_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="subscription", description="Моя подписка"),
)


async def setup_bot_commands(bot: Bot) -> None:
    """setMyCommands + MenuButtonCommands — список /start, /subscription в меню бота."""
    await bot.set_my_commands(list(USER_COMMANDS))
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.debug("Bot command menu configured: {}", [c.command for c in USER_COMMANDS])
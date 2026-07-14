"""Админ-команда /reboot — перезапуск systemd-служб бота."""
from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from services.bot_restart import trigger_bot_restart
from .admin_auth import is_admin

router = Router(name="admin_reboot")

_REPLY_DELAY_SEC = 1.5


async def _perform_reboot(message: Message) -> None:
    admin_id = message.from_user.id if message.from_user else 0
    try:
        await message.answer(
            "🔄 <b>Перезапуск служб бота</b>\n"
            "vpn-bot-telegram · vpn-bot-web\n\n"
            "<i>Связь оборвётся на несколько секунд.</i>\n"
            "<i>Если бот полностью завис (не отвечает на команды) — "
            "используйте <code>vpn-bot-ctl.sh</code> → пункт 3 на VPS.</i>",
        )
        await asyncio.sleep(_REPLY_DELAY_SEC)
        ok, detail = await trigger_bot_restart(reason=f"/reboot tg_id={admin_id}")
        if ok:
            logger.info("Restart OK: {}", detail)
            return
        await message.answer(
            "❌ <b>Не удалось перезапустить службы</b>\n"
            f"<code>{detail[:350]}</code>",
        )
    except Exception as e:
        logger.exception("Admin /reboot failed for tg_id={}: {}", admin_id, e)
        try:
            await message.answer(
                "❌ Ошибка перезапуска. "
                "На VPS: <code>sudo bash deploy/vpn-bot-ctl.sh restart</code>",
            )
        except Exception:
            pass


@router.message(Command("reboot"), StateFilter("*"))
async def cmd_reboot(message: Message, state: FSMContext) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await state.clear()
    logger.warning(
        "Priority /reboot от admin tg_id={} — сброс FSM, запуск рестарта",
        message.from_user.id,
    )
    asyncio.create_task(
        _perform_reboot(message),
        name=f"admin_reboot_{message.from_user.id}",
    )
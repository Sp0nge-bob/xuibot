"""Админка: бэкап базы и отправка архива в ЛС."""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from config.settings import settings
from db import bot_settings as bot_settings_db
from services.backup import send_backup_to_admins
from .admin_auth import is_admin
from .admin_keyboards import admin_backup_interval_edit_kb, admin_backup_kb
from .messages import admin_backup_interval_edit_prompt_text, admin_backup_menu_text
from .scheduler import reschedule_backup_job
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _backup_context() -> dict:
    interval = await bot_settings_db.get_backup_interval()
    backup_disabled = await bot_settings_db.is_backup_disabled()
    env_interval = bot_settings_db.parse_backup_interval_input(settings.BACKUP_INTERVAL) or "24h"
    return {
        "interval": interval,
        "interval_label": bot_settings_db.format_backup_interval_label(interval),
        "backup_disabled": backup_disabled,
        "interval_overridden": await bot_settings_db.is_backup_interval_overridden(),
        "backup_enabled": settings.BACKUP_ENABLED and not backup_disabled,
        "env_disabled": not settings.BACKUP_ENABLED,
        "env_interval": env_interval,
    }


async def _show_backup_menu(cb: CallbackQuery) -> None:
    ctx = await _backup_context()
    await send_or_edit(
        cb,
        admin_backup_menu_text(
            backup_enabled=ctx["backup_enabled"],
            interval=ctx["interval"],
            interval_label=ctx["interval_label"],
            local_retain=settings.BACKUP_LOCAL_RETAIN,
            env_disabled=ctx["env_disabled"],
            admin_disabled=ctx["backup_disabled"],
            interval_overridden=ctx["interval_overridden"],
            env_interval=ctx["env_interval"],
        ),
        admin_backup_kb(
            backup_enabled=ctx["backup_enabled"],
            env_disabled=ctx["env_disabled"],
            interval=ctx["interval"],
            interval_overridden=ctx["interval_overridden"],
        ),
    )


@router.callback_query(F.data == "adm:backup")
async def cb_admin_backup(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    await _show_backup_menu(cb)


@router.callback_query(F.data == "adm:backup:toggle")
async def cb_admin_backup_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    if not settings.BACKUP_ENABLED:
        await safe_cb_answer(cb, "Бэкап отключён в .env (BACKUP_ENABLED=false)", show_alert=True)
        return

    was_disabled = await bot_settings_db.is_backup_disabled()
    await bot_settings_db.set_backup_disabled(not was_disabled)
    await reschedule_backup_job()
    await safe_cb_answer(
        cb,
        "Автобэкап выключен" if not was_disabled else "Автобэкап включён",
    )
    await _show_backup_menu(cb)


@router.callback_query(F.data == "adm:backup:interval:edit")
async def cb_admin_backup_interval_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    if not settings.BACKUP_ENABLED:
        await safe_cb_answer(cb, "Бэкап отключён в .env", show_alert=True)
        return
    ctx = await _backup_context()
    await state.set_state(AdminStates.waiting_backup_interval)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_backup_interval_edit_prompt_text(
            interval=ctx["interval"],
            interval_label=ctx["interval_label"],
        ),
        admin_backup_interval_edit_kb(),
    )


@router.callback_query(F.data == "adm:backup:interval:reset")
async def cb_admin_backup_interval_reset(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    if not settings.BACKUP_ENABLED:
        await safe_cb_answer(cb, "Бэкап отключён в .env", show_alert=True)
        return
    await bot_settings_db.clear_backup_interval()
    interval = await reschedule_backup_job()
    label = bot_settings_db.format_backup_interval_label(interval or "24h")
    await safe_cb_answer(cb, f"Интервал из .env: {label}")
    await _show_backup_menu(cb)


@router.message(AdminStates.waiting_backup_interval)
async def msg_admin_backup_interval(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    interval = bot_settings_db.parse_backup_interval_input(message.text or "")
    if interval is None:
        await message.answer(
            "❌ Неверный интервал.\n\n"
            "Примеры: <code>30m</code>, <code>6h</code>, <code>24h</code>, <code>7d</code>\n"
            "Допустимо от 30m до 30d."
        )
        return

    await bot_settings_db.set_backup_interval(interval)
    await reschedule_backup_job()
    await state.clear()

    label = bot_settings_db.format_backup_interval_label(interval)
    ctx = await _backup_context()
    await message.answer(
        f"✅ Автобэкап: <b>{label}</b> (<code>{interval}</code>)",
        reply_markup=admin_backup_kb(
            backup_enabled=ctx["backup_enabled"],
            env_disabled=ctx["env_disabled"],
            interval=ctx["interval"],
            interval_overridden=ctx["interval_overridden"],
        ),
    )


@router.callback_query(F.data == "adm:backup:now")
async def cb_admin_backup_now(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb, "Создаём архив…")
    await send_or_edit(cb, "⏳ <b>Создаём бэкап…</b>\n\nАрхив будет отправлен вам в ЛС.")
    try:
        result = await send_backup_to_admins(source="manual")
    except Exception as e:
        logger.exception("Manual backup failed: {}", e)
        ctx = await _backup_context()
        await send_or_edit(
            cb,
            f"❌ Ошибка бэкапа: <code>{str(e)[:200]}</code>",
            admin_backup_kb(
                backup_enabled=ctx["backup_enabled"],
                env_disabled=ctx["env_disabled"],
                interval=ctx["interval"],
                interval_overridden=ctx["interval_overridden"],
            ),
        )
        return

    if result.get("ok"):
        text = (
            "✅ <b>Бэкап отправлен</b>\n\n"
            f"Доставлено админам: <b>{result['sent']}</b> из <b>{result['total']}</b>\n"
            f"Файл: <code>{result['archive']}</code>"
        )
    else:
        text = (
            "❌ <b>Не удалось отправить бэкап</b>\n\n"
            f"<code>{result.get('reason', 'unknown')}</code>"
        )
        if result.get("errors"):
            text += "\n" + "\n".join(f"• {e}"[:120] for e in result["errors"][:3])

    ctx = await _backup_context()
    await send_or_edit(
        cb,
        text,
        admin_backup_kb(
            backup_enabled=ctx["backup_enabled"],
            env_disabled=ctx["env_disabled"],
            interval=ctx["interval"],
            interval_overridden=ctx["interval_overridden"],
        ),
    )
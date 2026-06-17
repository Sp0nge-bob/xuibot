"""Админка: бэкап базы и отправка архива в ЛС."""
from aiogram import Router, F
from aiogram.types import CallbackQuery
from loguru import logger

from config.settings import settings
from db import bot_settings as bot_settings_db
from services.backup import send_backup_to_admins
from .admin_auth import is_admin
from .admin_keyboards import admin_backup_kb
from .messages import admin_backup_menu_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _show_backup_menu(cb: CallbackQuery) -> None:
    backup_disabled = await bot_settings_db.is_backup_disabled()
    await send_or_edit(
        cb,
        admin_backup_menu_text(
            backup_enabled=settings.BACKUP_ENABLED and not backup_disabled,
            hour_utc=settings.BACKUP_HOUR_UTC,
            local_retain=settings.BACKUP_LOCAL_RETAIN,
            env_disabled=not settings.BACKUP_ENABLED,
            admin_disabled=backup_disabled,
        ),
        admin_backup_kb(
            backup_enabled=settings.BACKUP_ENABLED and not backup_disabled,
            env_disabled=not settings.BACKUP_ENABLED,
        ),
    )


@router.callback_query(F.data == "adm:backup")
async def cb_admin_backup(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
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
    await safe_cb_answer(
        cb,
        "Ежедневный бэкап выключен" if not was_disabled else "Ежедневный бэкап включён",
    )
    await _show_backup_menu(cb)


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
        await send_or_edit(
            cb,
            f"❌ Ошибка бэкапа: <code>{str(e)[:200]}</code>",
            admin_backup_kb(backup_enabled=settings.BACKUP_ENABLED, env_disabled=not settings.BACKUP_ENABLED),
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

    backup_disabled = await bot_settings_db.is_backup_disabled()
    await send_or_edit(
        cb,
        text,
        admin_backup_kb(
            backup_enabled=settings.BACKUP_ENABLED and not backup_disabled,
            env_disabled=not settings.BACKUP_ENABLED,
        ),
    )
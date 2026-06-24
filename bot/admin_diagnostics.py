"""Админка: диагностика работоспособности системы."""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from services.admin_diagnostics import collect_diagnostics, format_diagnostics_text
from .admin_auth import is_admin
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def diagnostics_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:diagnostics:refresh")],
        [InlineKeyboardButton(text="« Админ-панель", callback_data="adm:menu")],
    ])


async def _show_diagnostics(cb: CallbackQuery, *, refresh: bool) -> None:
    from bot import bot

    await safe_cb_answer(cb, "Обновляем…" if refresh else None)
    await send_or_edit(
        cb,
        "⏳ <b>Диагностика…</b>\n\nПроверяем ноды, webhook и сервисы…",
        diagnostics_kb(),
    )

    try:
        report = await collect_diagnostics(bot=bot, full_node_check=True)
        text = format_diagnostics_text(report)
    except Exception as e:
        logger.exception("Admin diagnostics failed: {}", e)
        text = (
            "❌ <b>Ошибка диагностики</b>\n\n"
            f"<code>{type(e).__name__}: {str(e)[:200]}</code>"
        )

    await send_or_edit(cb, text, diagnostics_kb())


@router.callback_query(F.data == "adm:diagnostics")
async def cb_admin_diagnostics(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await _show_diagnostics(cb, refresh=False)


@router.callback_query(F.data == "adm:diagnostics:refresh")
async def cb_admin_diagnostics_refresh(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    await _show_diagnostics(cb, refresh=True)
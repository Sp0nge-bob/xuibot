"""Админка: выгрузка последних N строк логов в .txt."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from loguru import logger

from services.log_export import (
    LOG_TAIL_MAX_LINES,
    LOG_TAIL_MIN_LINES,
    LOG_TAIL_PRESETS,
    export_log_tail,
    parse_log_tail_count,
    resolve_active_log_path,
)
from ui.theme import screen
from .admin_auth import is_admin
from .admin_keyboards import admin_logs_custom_kb, admin_logs_kb
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def admin_logs_menu_text() -> str:
    path = resolve_active_log_path()
    if path is None:
        source = "файл не найден"
        size_line = "Размер: —"
    else:
        try:
            size = path.stat().st_size
            size_line = f"Размер: <b>{_format_size(size)}</b>"
        except OSError:
            size_line = "Размер: —"
        source = str(path)

    presets = ", ".join(str(n) for n in LOG_TAIL_PRESETS)
    return screen(
        "📋 <b>Логи</b>",
        f"Источник: <code>{source}</code>\n{size_line}",
        f"Выберите, сколько последних строк выгрузить в <code>.txt</code>.\n"
        f"Пресеты: <b>{presets}</b> или своё число "
        f"({LOG_TAIL_MIN_LINES}–{LOG_TAIL_MAX_LINES}).",
        footer="⚠️ <i>В логах могут быть tx_id, tg_id, хосты панелей — не пересылайте файл.</i>",
    )


async def _show_logs_menu(cb: CallbackQuery) -> None:
    await send_or_edit(cb, admin_logs_menu_text(), admin_logs_kb())


async def _send_log_tail(chat_id: int, lines: int) -> str:
    """Собрать tail и отправить документ. Возвращает текст статуса для UI."""
    from bot import bot

    export = export_log_tail(lines)
    doc = BufferedInputFile(export.content, filename=export.filename)
    caption_parts = [
        f"📋 Логи: последние <b>{export.lines_returned}</b> строк",
    ]
    if export.lines_returned < export.lines_requested:
        caption_parts.append(
            f"(запрошено {export.lines_requested} — в файле меньше)"
        )
    if export.truncated_by_size:
        caption_parts.append("⚠️ обрезано по лимиту размера")
    caption = "\n".join(caption_parts)
    if len(caption) > 1024:
        caption = caption[:1020] + "…"

    await bot.send_document(chat_id, doc, caption=caption)

    status = (
        f"✅ <b>Файл отправлен</b>\n\n"
        f"• Строк: <b>{export.lines_returned}</b>"
        f" / {export.lines_requested}\n"
        f"• Размер: <b>{_format_size(len(export.content))}</b>\n"
        f"• Имя: <code>{export.filename}</code>\n"
        f"• Источник: <code>{export.source_path.name}</code>"
    )
    if export.truncated_by_size:
        status += "\n\n⚠️ Выгрузка урезана по лимиту размера файла."
    return status


@router.callback_query(F.data == "adm:logs")
async def cb_admin_logs(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    await _show_logs_menu(cb)


@router.callback_query(F.data.startswith("adm:logs:tail:"))
async def cb_admin_logs_tail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return

    raw = (cb.data or "").rsplit(":", 1)[-1]
    lines = parse_log_tail_count(raw)
    if lines is None:
        await safe_cb_answer(cb, "Неверное число строк", show_alert=True)
        return

    await state.clear()
    await safe_cb_answer(cb, f"Собираем {lines} строк…")
    await send_or_edit(
        cb,
        screen(
            "📋 <b>Логи</b>",
            f"⏳ Читаем последние <b>{lines}</b> строк…",
        ),
        admin_logs_kb(),
    )

    try:
        status = await _send_log_tail(cb.from_user.id, lines)
    except FileNotFoundError as e:
        await send_or_edit(
            cb,
            screen("❌ <b>Лог не найден</b>", str(e)),
            admin_logs_kb(),
        )
        return
    except Exception as e:
        logger.exception("Admin log export failed ({} lines): {}", lines, e)
        await send_or_edit(
            cb,
            screen(
                "❌ <b>Ошибка выгрузки</b>",
                f"<code>{type(e).__name__}: {str(e)[:200]}</code>",
            ),
            admin_logs_kb(),
        )
        return

    await send_or_edit(cb, status, admin_logs_kb())


@router.callback_query(F.data == "adm:logs:custom")
async def cb_admin_logs_custom(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_log_lines_count)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        screen(
            "📋 <b>Своё число строк</b>",
            f"Отправьте число от <b>{LOG_TAIL_MIN_LINES}</b> "
            f"до <b>{LOG_TAIL_MAX_LINES}</b>.\n\n"
            "Примеры: <code>250</code>, <code>2000</code>, <code>10k</code>",
        ),
        admin_logs_custom_kb(),
    )


@router.message(AdminStates.waiting_log_lines_count)
async def msg_admin_logs_custom(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    lines = parse_log_tail_count(message.text)
    if lines is None:
        await message.answer(
            f"❌ Укажите целое число от {LOG_TAIL_MIN_LINES} "
            f"до {LOG_TAIL_MAX_LINES} (можно <code>5k</code>)."
        )
        return

    await state.clear()
    wait_msg = await message.answer(
        f"⏳ Читаем последние <b>{lines}</b> строк…"
    )

    try:
        status = await _send_log_tail(message.from_user.id, lines)
    except FileNotFoundError as e:
        await wait_msg.edit_text(
            screen("❌ <b>Лог не найден</b>", str(e)),
            reply_markup=admin_logs_kb(),
        )
        return
    except Exception as e:
        logger.exception("Admin log export (custom) failed: {}", e)
        await wait_msg.edit_text(
            screen(
                "❌ <b>Ошибка выгрузки</b>",
                f"<code>{type(e).__name__}: {str(e)[:200]}</code>",
            ),
            reply_markup=admin_logs_kb(),
        )
        return

    await wait_msg.edit_text(status, reply_markup=admin_logs_kb())

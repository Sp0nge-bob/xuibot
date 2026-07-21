"""Админка: выгрузка последних N строк логов (текущий + архивы) в .txt."""
from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from loguru import logger

from services.log_export import (
    LOG_TAIL_MAX_LINES,
    LOG_TAIL_MIN_LINES,
    LOG_TAIL_PRESETS,
    LogSource,
    export_log_tail,
    get_log_source,
    list_log_sources,
    parse_log_tail_count,
)
from ui.theme import screen
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_logs_custom_kb,
    admin_logs_sources_kb,
    admin_logs_tail_kb,
)
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _format_mtime(ts: float) -> str:
    if ts <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


def admin_logs_menu_text(sources: list[LogSource]) -> str:
    if not sources:
        body = (
            "В <code>data/logs/</code> пока нет файлов.\n"
            "После работы бота появится <code>bot.log</code>, "
            "после рестарта — архивы <code>botlog_*.log</code> "
            "(до <code>LOG_ARCHIVE_RETAIN</code>)."
        )
    else:
        lines = []
        for s in sources:
            kind = "сейчас" if s.is_active else "архив"
            lines.append(
                f"• {s.label}\n"
                f"  <code>{s.path.name}</code> · {_format_size(s.size_bytes)}"
                f" · {_format_mtime(s.mtime)} · <i>{kind}</i>"
            )
        body = "\n".join(lines)

    return screen(
        "📋 <b>Логи</b>",
        body,
        "Выберите файл, затем число последних строк для выгрузки в <code>.txt</code>.",
        footer="⚠️ <i>В логах могут быть tx_id, tg_id, хосты — не пересылайте файл.</i>",
    )


def admin_logs_tail_menu_text(source: LogSource) -> str:
    presets = ", ".join(str(n) for n in LOG_TAIL_PRESETS)
    kind = "текущая сессия" if source.is_active else "архив после рестарта"
    return screen(
        "📋 <b>Выгрузка логов</b>",
        f"{source.label}\n"
        f"<code>{source.path.name}</code>\n"
        f"Размер: <b>{_format_size(source.size_bytes)}</b> · "
        f"{_format_mtime(source.mtime)}\n"
        f"<i>{kind}</i>",
        f"Сколько последних строк выгрузить?\n"
        f"Пресеты: <b>{presets}</b> или своё число "
        f"({LOG_TAIL_MIN_LINES}–{LOG_TAIL_MAX_LINES}).",
        footer="⚠️ <i>Не пересылайте файл третьим лицам.</i>",
    )


async def _show_sources_menu(cb: CallbackQuery) -> None:
    sources = list_log_sources()
    await send_or_edit(
        cb,
        admin_logs_menu_text(sources),
        admin_logs_sources_kb(sources),
    )


async def _show_tail_menu(cb: CallbackQuery, source: LogSource) -> None:
    await send_or_edit(
        cb,
        admin_logs_tail_menu_text(source),
        admin_logs_tail_kb(source.id),
    )


async def _send_log_tail(chat_id: int, lines: int, source_id: str) -> str:
    """Собрать tail и отправить документ. Возвращает текст статуса для UI."""
    from bot import bot

    export = export_log_tail(lines, source_id=source_id)
    doc = BufferedInputFile(export.content, filename=export.filename)
    caption_parts = [
        f"📋 <b>{export.source_path.name}</b>",
        f"последние <b>{export.lines_returned}</b> строк",
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
        f"• Источник: <code>{export.source_path.name}</code>\n"
        f"• Строк: <b>{export.lines_returned}</b>"
        f" / {export.lines_requested}\n"
        f"• Размер: <b>{_format_size(len(export.content))}</b>\n"
        f"• Имя: <code>{export.filename}</code>"
    )
    if export.truncated_by_size:
        status += "\n\n⚠️ Выгрузка урезана по лимиту размера файла."
    return status


def _parse_source_id(raw: str | None) -> str | None:
    sid = (raw or "").strip()
    if get_log_source(sid) is None and sid != "active":
        # active может отсутствовать — всё равно вернём для сообщений об ошибке
        if not sid or not (
            sid == "active" or (sid.startswith("arch") and sid[4:].isdigit())
        ):
            return None
    if sid == "active" or (sid.startswith("arch") and sid[4:].isdigit()):
        return sid
    return None


@router.callback_query(F.data == "adm:logs")
async def cb_admin_logs(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.clear()
    await safe_cb_answer(cb)
    await _show_sources_menu(cb)


@router.callback_query(F.data.startswith("adm:logs:src:"))
async def cb_admin_logs_src(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return

    source_id = (cb.data or "").split(":", 3)[-1]
    source = get_log_source(source_id)
    if source is None:
        await safe_cb_answer(cb, "Файл не найден (возможно, удалён)", show_alert=True)
        await state.clear()
        await _show_sources_menu(cb)
        return

    await state.clear()
    await state.update_data(log_source_id=source.id)
    await safe_cb_answer(cb)
    await _show_tail_menu(cb, source)


@router.callback_query(F.data.startswith("adm:logs:tail:"))
async def cb_admin_logs_tail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return

    # adm:logs:tail:{source_id}:{n}
    parts = (cb.data or "").split(":")
    if len(parts) < 5:
        await safe_cb_answer(cb, "Неверный запрос", show_alert=True)
        return
    source_id = parts[3]
    lines = parse_log_tail_count(parts[4])
    if lines is None or _parse_source_id(source_id) is None:
        await safe_cb_answer(cb, "Неверные параметры", show_alert=True)
        return

    source = get_log_source(source_id)
    await state.clear()
    await safe_cb_answer(cb, f"Собираем {lines} строк…")

    loading_kb = admin_logs_tail_kb(source_id) if source else admin_logs_sources_kb(list_log_sources())
    await send_or_edit(
        cb,
        screen(
            "📋 <b>Логи</b>",
            f"⏳ Читаем последние <b>{lines}</b> строк"
            + (f" из <code>{source.path.name}</code>…" if source else "…"),
        ),
        loading_kb,
    )

    try:
        status = await _send_log_tail(cb.from_user.id, lines, source_id)
    except FileNotFoundError as e:
        await send_or_edit(
            cb,
            screen("❌ <b>Лог не найден</b>", str(e)),
            admin_logs_sources_kb(list_log_sources()),
        )
        return
    except Exception as e:
        logger.exception(
            "Admin log export failed ({} lines, {}): {}", lines, source_id, e,
        )
        await send_or_edit(
            cb,
            screen(
                "❌ <b>Ошибка выгрузки</b>",
                f"<code>{type(e).__name__}: {str(e)[:200]}</code>",
            ),
            loading_kb,
        )
        return

    await send_or_edit(
        cb,
        status,
        admin_logs_tail_kb(source_id) if get_log_source(source_id) else admin_logs_sources_kb(list_log_sources()),
    )


@router.callback_query(F.data.startswith("adm:logs:custom:"))
async def cb_admin_logs_custom(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return

    source_id = (cb.data or "").split(":", 3)[-1]
    source = get_log_source(source_id)
    if source is None:
        await safe_cb_answer(cb, "Файл не найден", show_alert=True)
        await _show_sources_menu(cb)
        return

    await state.set_state(AdminStates.waiting_log_lines_count)
    await state.update_data(log_source_id=source.id)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        screen(
            "📋 <b>Своё число строк</b>",
            f"Файл: <code>{source.path.name}</code>\n\n"
            f"Отправьте число от <b>{LOG_TAIL_MIN_LINES}</b> "
            f"до <b>{LOG_TAIL_MAX_LINES}</b>.\n\n"
            "Примеры: <code>250</code>, <code>2000</code>, <code>10k</code>",
        ),
        admin_logs_custom_kb(source.id),
    )


@router.message(AdminStates.waiting_log_lines_count)
async def msg_admin_logs_custom(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    data = await state.get_data()
    source_id = data.get("log_source_id") or "active"
    if _parse_source_id(str(source_id)) is None:
        source_id = "active"

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
        status = await _send_log_tail(message.from_user.id, lines, str(source_id))
    except FileNotFoundError as e:
        await wait_msg.edit_text(
            screen("❌ <b>Лог не найден</b>", str(e)),
            reply_markup=admin_logs_sources_kb(list_log_sources()),
        )
        return
    except Exception as e:
        logger.exception("Admin log export (custom) failed: {}", e)
        await wait_msg.edit_text(
            screen(
                "❌ <b>Ошибка выгрузки</b>",
                f"<code>{type(e).__name__}: {str(e)[:200]}</code>",
            ),
            reply_markup=admin_logs_tail_kb(str(source_id)),
        )
        return

    kb = (
        admin_logs_tail_kb(str(source_id))
        if get_log_source(str(source_id))
        else admin_logs_sources_kb(list_log_sources())
    )
    await wait_msg.edit_text(status, reply_markup=kb)

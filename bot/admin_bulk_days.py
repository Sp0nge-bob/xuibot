"""Админка: добавить дни всем активным подпискам (БД + bulkAdjust)."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from db import database as db
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_back_kb,
    admin_bulk_days_cancel_kb,
    admin_bulk_days_confirm_kb,
    admin_bulk_days_kb,
)
from .messages import (
    admin_bulk_days_confirm_text,
    admin_bulk_days_custom_prompt_text,
    admin_bulk_days_done_text,
    admin_bulk_days_empty_text,
    admin_bulk_days_menu_text,
)
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_MAX_DAYS = 3650
_job_running = False


async def _cancel_to_admin(message: Message, state: FSMContext) -> bool:
    raw = message.text or ""
    if not raw.strip().startswith("/"):
        return False
    cmd = raw.strip().split()[0].split("@")[0].lower()
    if cmd != "/admin":
        await message.answer("Ввод отменён.")
        await state.set_state(None)
        return True
    await state.set_state(None)
    from bot.admin import _admin_menu_text, admin_menu_kb

    await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
    return True


async def _show_menu(target: CallbackQuery | Message, state: FSMContext) -> None:
    await state.set_state(None)
    subs = await db.get_all_active_subscriptions()
    if not subs:
        text = admin_bulk_days_empty_text()
        kb = admin_back_kb()
    else:
        text = admin_bulk_days_menu_text(sub_count=len(subs))
        kb = admin_bulk_days_kb()
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


def _parse_days(raw: str) -> int | None:
    text = (raw or "").strip()
    if not text.isdigit():
        return None
    days = int(text)
    if days <= 0 or days > _MAX_DAYS:
        return None
    return days


@router.callback_query(F.data == "adm:bulk_days")
async def cb_admin_bulk_days(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_menu(cb, state)


@router.callback_query(F.data == "adm:bulk_days:custom")
async def cb_admin_bulk_days_custom(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    subs = await db.get_all_active_subscriptions()
    if not subs:
        await safe_cb_answer(cb, "Нет активных подписок", show_alert=True)
        await _show_menu(cb, state)
        return
    await state.set_state(AdminStates.waiting_bulk_days_custom)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_bulk_days_custom_prompt_text(),
        admin_bulk_days_cancel_kb(),
    )


@router.callback_query(F.data.startswith("adm:bulk_days:pick:"))
async def cb_admin_bulk_days_pick(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    days = _parse_days(cb.data.rsplit(":", 1)[-1])
    if days is None:
        await safe_cb_answer(cb, "Некорректный срок", show_alert=True)
        return
    subs = await db.get_all_active_subscriptions()
    if not subs:
        await safe_cb_answer(cb, "Нет активных подписок", show_alert=True)
        await _show_menu(cb, state)
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_bulk_days_confirm_text(days=days, sub_count=len(subs)),
        admin_bulk_days_confirm_kb(days),
    )


@router.message(AdminStates.waiting_bulk_days_custom)
async def msg_admin_bulk_days_custom(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    days = _parse_days(message.text or "")
    if days is None:
        await message.answer(
            f"❌ Введите целое число от 1 до {_MAX_DAYS}.",
            reply_markup=admin_bulk_days_cancel_kb(),
        )
        return
    subs = await db.get_all_active_subscriptions()
    await state.set_state(None)
    if not subs:
        await message.answer(admin_bulk_days_empty_text(), reply_markup=admin_back_kb())
        return
    await message.answer(
        admin_bulk_days_confirm_text(days=days, sub_count=len(subs)),
        reply_markup=admin_bulk_days_confirm_kb(days),
    )


@router.callback_query(F.data.startswith("adm:bulk_days:do:"))
async def cb_admin_bulk_days_do(cb: CallbackQuery, state: FSMContext):
    global _job_running
    if not is_admin(cb.from_user.id):
        return
    if _job_running:
        await safe_cb_answer(cb, "Продление уже выполняется", show_alert=True)
        return
    days = _parse_days(cb.data.rsplit(":", 1)[-1])
    if days is None:
        await safe_cb_answer(cb, "Некорректный срок", show_alert=True)
        return
    await state.set_state(None)
    await safe_cb_answer(cb, "Запускаю…")
    _job_running = True

    from bot import bot as app_bot
    from services.admin_bulk_extend import bulk_add_days_to_all_active

    admin_id = cb.from_user.id
    status = await cb.message.answer("⏰ Продлеваю на панели и в базе…")

    async def _run() -> None:
        global _job_running
        try:
            result = await bulk_add_days_to_all_active(days, admin_tg_id=admin_id)
            notify_ids: list[int] = list(result.get("notify_ids") or [])
            notify_text = str(result.get("notify_text") or "")
            notified = 0
            notify_failed = 0
            if notify_ids and notify_text:
                try:
                    await app_bot.edit_message_text(
                        "⏰ Сроки обновлены, рассылаю уведомления…",
                        chat_id=status.chat.id,
                        message_id=status.message_id,
                    )
                except Exception:
                    pass
                for uid in notify_ids:
                    try:
                        await app_bot.send_message(uid, notify_text)
                        notified += 1
                    except Exception:
                        notify_failed += 1
                    await asyncio.sleep(0.05)
            text = admin_bulk_days_done_text(
                days=days,
                db_updated=int(result.get("db_updated") or 0),
                panel_adjusted=int(result.get("panel_adjusted") or 0),
                panel_skipped=int(result.get("panel_skipped") or 0),
                notified=notified,
                notify_failed=notify_failed,
            )
            try:
                await app_bot.edit_message_text(
                    text,
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    reply_markup=admin_bulk_days_kb(),
                )
            except Exception:
                await app_bot.send_message(
                    admin_id, text, reply_markup=admin_bulk_days_kb(),
                )
        except ValueError as e:
            try:
                await app_bot.edit_message_text(
                    f"❌ {e}",
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    reply_markup=admin_bulk_days_kb(),
                )
            except Exception:
                await app_bot.send_message(admin_id, f"❌ {e}")
        except Exception as e:
            logger.exception("Bulk days job failed: {}", e)
            try:
                await app_bot.send_message(admin_id, f"❌ Массовое продление оборвалось: {e}")
            except Exception:
                pass
        finally:
            _job_running = False

    asyncio.create_task(_run(), name="admin_bulk_days")

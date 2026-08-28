"""Админка: массовое объявление всем пользователям бота."""
from __future__ import annotations

import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger

from db import database as db
from ui.compliance import compliance_error_message
from .admin_auth import is_admin
from .admin_keyboards import admin_broadcast_confirm_kb, admin_broadcast_prompt_kb
from .messages import (
    admin_broadcast_confirm_text,
    admin_broadcast_done_text,
    admin_broadcast_empty_users_text,
    admin_broadcast_progress_text,
    admin_broadcast_prompt_text,
)
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_ALBUM_WAIT_SEC = 0.9
_album_buf: dict[int, list[Message]] = {}
_album_tasks: dict[int, asyncio.Task] = {}
_broadcast_running = False


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


def _message_text_for_compliance(message: Message) -> str:
    return (message.text or message.caption or "").strip()


async def _show_prompt(target: CallbackQuery | Message, state: FSMContext) -> None:
    await state.set_state(AdminStates.waiting_broadcast_message)
    await state.update_data(broadcast_chat_id=None, broadcast_message_ids=[])
    users = await db.list_user_tg_ids()
    if not users:
        text = admin_broadcast_empty_users_text()
    else:
        text = admin_broadcast_prompt_text(user_count=len(users))
    kb = admin_broadcast_prompt_kb()
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _offer_preview(messages: list[Message], state: FSMContext) -> None:
    if not messages:
        return
    first = messages[0]
    bot = first.bot
    admin_id = first.from_user.id if first.from_user else 0
    users = await db.list_user_tg_ids()
    if not users:
        await first.answer(admin_broadcast_empty_users_text())
        return

    copied_ids: list[int] = []
    for src in messages:
        copied = await bot.copy_message(
            chat_id=first.chat.id,
            from_chat_id=src.chat.id,
            message_id=src.message_id,
        )
        copied_ids.append(copied.message_id)

    await state.update_data(
        broadcast_chat_id=first.chat.id,
        broadcast_message_ids=[int(m.message_id) for m in messages],
        broadcast_admin_id=admin_id,
    )
    await first.answer(
        admin_broadcast_confirm_text(parts=len(copied_ids), user_count=len(users)),
        reply_markup=admin_broadcast_confirm_kb(),
    )


def _schedule_album(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    _album_buf.setdefault(uid, []).append(message)
    old = _album_tasks.get(uid)
    if old and not old.done():
        old.cancel()

    async def _flush() -> None:
        try:
            await asyncio.sleep(_ALBUM_WAIT_SEC)
        except asyncio.CancelledError:
            return
        msgs = _album_buf.pop(uid, [])
        _album_tasks.pop(uid, None)
        if not msgs:
            return
        msgs.sort(key=lambda m: m.message_id)
        await _offer_preview(msgs, state)

    _album_tasks[uid] = asyncio.create_task(_flush())


@router.callback_query(F.data == "adm:broadcast")
async def cb_admin_broadcast(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_prompt(cb, state)


@router.message(AdminStates.waiting_broadcast_message)
async def msg_admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    if message.content_type in {"pinned_message", "new_chat_members", "left_chat_member"}:
        await message.answer("Это служебное сообщение нельзя разослать. Пришлите обычное.")
        return
    compliance = compliance_error_message(_message_text_for_compliance(message))
    if compliance:
        await message.answer(compliance)
        return
    if message.media_group_id:
        _schedule_album(message, state)
        return
    try:
        await _offer_preview([message], state)
    except Exception as e:
        logger.warning("Broadcast preview failed: {}", e)
        await message.answer("Не удалось скопировать это сообщение. Пришлите текст или фото.")


@router.callback_query(F.data == "adm:broadcast:send")
async def cb_admin_broadcast_send(cb: CallbackQuery, state: FSMContext):
    global _broadcast_running
    if not is_admin(cb.from_user.id):
        return
    if _broadcast_running:
        await safe_cb_answer(cb, "Рассылка уже идёт", show_alert=True)
        return
    data = await state.get_data()
    from_chat_id = data.get("broadcast_chat_id")
    message_ids = list(data.get("broadcast_message_ids") or [])
    skip_id = int(data.get("broadcast_admin_id") or cb.from_user.id)
    if not from_chat_id or not message_ids:
        await safe_cb_answer(cb, "Сначала пришлите сообщение", show_alert=True)
        await _show_prompt(cb, state)
        return

    users = await db.list_user_tg_ids()
    await state.set_state(None)
    await safe_cb_answer(cb, "Рассылка запущена")
    _broadcast_running = True

    from bot import bot as app_bot
    from services.broadcast import copy_announcement_to_users

    targets = [uid for uid in users if int(uid) != skip_id]
    status = await cb.message.answer(
        admin_broadcast_progress_text(sent=0, failed=0, total=len(targets)),
    )

    async def _run() -> None:
        global _broadcast_running
        try:
            async def _progress(sent: int, failed: int, total: int) -> None:
                try:
                    await app_bot.edit_message_text(
                        admin_broadcast_progress_text(sent=sent, failed=failed, total=total),
                        chat_id=status.chat.id,
                        message_id=status.message_id,
                    )
                except Exception:
                    pass

            stats = await copy_announcement_to_users(
                app_bot,
                from_chat_id=int(from_chat_id),
                message_ids=[int(x) for x in message_ids],
                user_ids=users,
                skip_ids={skip_id},
                on_progress=_progress,
            )
            try:
                await app_bot.edit_message_text(
                    admin_broadcast_done_text(
                        sent=int(stats["sent"]),
                        failed=int(stats["failed"]),
                        total=int(stats["total"]),
                    ),
                    chat_id=status.chat.id,
                    message_id=status.message_id,
                    reply_markup=admin_broadcast_prompt_kb(),
                )
            except Exception:
                await app_bot.send_message(
                    skip_id,
                    admin_broadcast_done_text(
                        sent=int(stats["sent"]),
                        failed=int(stats["failed"]),
                        total=int(stats["total"]),
                    ),
                    reply_markup=admin_broadcast_prompt_kb(),
                )
        except Exception as e:
            logger.exception("Broadcast job failed: {}", e)
            try:
                await app_bot.send_message(skip_id, f"❌ Рассылка оборвалась: {e}")
            except Exception:
                pass
        finally:
            _broadcast_running = False

    asyncio.create_task(_run(), name="admin_broadcast")

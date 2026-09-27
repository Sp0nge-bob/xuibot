"""Админ-панель: управление бонусом за первую привязку email к Telegram."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import bot_settings as bot_settings_db
from .admin_auth import is_admin
from .admin_keyboards import admin_back_kb
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


def _email_bonus_kb(*, enabled: bool, days: int) -> InlineKeyboardMarkup:
    toggle_text = "🔴 Выключить бонус" if enabled else "🟢 Включить бонус"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=toggle_text,
                    callback_data="adm:email_bonus:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"✏️ Изменить дни (сейчас: {days} дн.)",
                    callback_data="adm:email_bonus:edit_days",
                )
            ],
            [
                InlineKeyboardButton(text="1 дн.", callback_data="adm:email_bonus:set:1"),
                InlineKeyboardButton(text="3 дн.", callback_data="adm:email_bonus:set:3"),
                InlineKeyboardButton(text="7 дн.", callback_data="adm:email_bonus:set:7"),
                InlineKeyboardButton(text="14 дн.", callback_data="adm:email_bonus:set:14"),
                InlineKeyboardButton(text="30 дн.", callback_data="adm:email_bonus:set:30"),
            ],
            [
                InlineKeyboardButton(
                    text="« К разделу «Клиенты»",
                    callback_data="adm:hub:clients",
                )
            ],
        ]
    )


def _email_bonus_text(*, enabled: bool, days: int) -> str:
    status_str = "🟢 <b>Включен</b>" if enabled else "🔴 <b>Выключен</b>"
    return (
        "🎁 <b>Бонус за первую привязку email</b>\n\n"
        f"<b>Статус:</b> {status_str}\n"
        f"<b>Количество добавляемых дней:</b> <b>+{days} дн.</b>\n\n"
        "<i>Если клиент, который ранее никогда не привязывал email к Telegram-аккаунту, "
        "успешно привяжет почту, он автоматически получит указанное количество дней "
        "ко всем своим существующим подпискам.\n\n"
        "Защита от злоупотреблений: при отвязке и повторной привязке бонус повторно не начисляется.</i>"
    )


async def _show_email_bonus_menu(target: CallbackQuery | Message) -> None:
    enabled = await bot_settings_db.get_email_bonus_enabled()
    days = await bot_settings_db.get_email_bonus_days()
    text = _email_bonus_text(enabled=enabled, days=days)
    kb = _email_bonus_kb(enabled=enabled, days=days)

    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:email_bonus")
async def cb_admin_email_bonus(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_email_bonus_menu(cb)


@router.callback_query(F.data == "adm:email_bonus:toggle")
async def cb_admin_email_bonus_toggle(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    current = await bot_settings_db.get_email_bonus_enabled()
    new_val = not current
    await bot_settings_db.set_email_bonus_enabled(new_val)
    msg = "Бонус включен" if new_val else "Бонус выключен"
    await safe_cb_answer(cb, msg)
    await _show_email_bonus_menu(cb)


@router.callback_query(F.data.startswith("adm:email_bonus:set:"))
async def cb_admin_email_bonus_set(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    try:
        days = int(cb.data.split(":")[-1])
        await bot_settings_db.set_email_bonus_days(days)
        await safe_cb_answer(cb, f"Установлено: +{days} дн.")
    except Exception:
        await safe_cb_answer(cb, "Ошибка установки дней")
    await _show_email_bonus_menu(cb)


@router.callback_query(F.data == "adm:email_bonus:edit_days")
async def cb_admin_email_bonus_edit_days(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    current_days = await bot_settings_db.get_email_bonus_days()
    await state.set_state(AdminStates.waiting_email_bonus_days)
    await safe_cb_answer(cb)
    cancel_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:email_bonus")]
        ]
    )
    prompt = (
        f"Введите количество дней (от 1 до 365), которое будет начисляться "
        f"при первой привязке email.\n\nТекущее значение: <b>{current_days}</b> дн."
    )
    await send_or_edit(cb, prompt, cancel_kb)


@router.message(AdminStates.waiting_email_bonus_days)
async def msg_admin_email_bonus_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    try:
        val = int(text)
        if not (1 <= val <= 365):
            raise ValueError()
    except ValueError:
        await message.answer(
            "❌ Введите целое число от 1 до 365:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:email_bonus")]
                ]
            ),
        )
        return

    await bot_settings_db.set_email_bonus_days(val)
    await state.set_state(None)
    await message.answer(f"✅ Установлено: <b>+{val} дн.</b> бонуса за привязку email.")
    await _show_email_bonus_menu(message)

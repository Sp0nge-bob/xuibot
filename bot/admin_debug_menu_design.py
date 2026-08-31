"""TEMP_MENU_DESIGN: админ-переключатель макетов /start. Потом вырезать."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import bot_settings as settings_db
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db import tickets as tickets_db
from services.payment_pending import get_resumable_pending_order
from services.subscription_sync import get_active_subscriptions_for_ui
from services.test_mode import is_test_mode
from ui.menu_designs import (
    CLASSIC,
    DESIGNS,
    design_label,
    get_menu_design_id,
    normalize_design_id,
    set_menu_design_id,
)
from .admin_auth import is_debug_admin
from .messages import main_menu_text
from .telegram_html import safe_html_fragment
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

_PREVIEW_LIMIT = 1800


def _design_kb(current: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for design_id, label in DESIGNS.items():
        mark = "· " if design_id == current else ""
        pair.append(InlineKeyboardButton(
            text=f"{mark}{label}",
            callback_data=f"adm:debug:ui:set:{design_id}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton(text="« К отладке", callback_data="adm:debug:enter")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _picker_text(*, current: str, preview: str) -> str:
    clipped = preview if len(preview) <= _PREVIEW_LIMIT else preview[: _PREVIEW_LIMIT - 1] + "…"
    return (
        "🎨 <b>Дизайн /start</b> <i>(тест, потом вырежем)</i>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"Сейчас: <b>{design_label(current)}</b> (<code>{current}</code>)\n"
        "Видно только админам (ваш /start). Клиенты остаются на классике.\n"
        "Работает при <code>ALLOW_DEBUG_ADMIN</code>.\n\n"
        "Превью с вашими данными:\n"
        f"<code>────────</code>\n"
        f"{clipped}\n"
        f"<code>────────</code>\n\n"
        "Или откройте /start — там те же кнопки."
    )


async def _preview_text(cb: CallbackQuery, design_id: str) -> str:
    user = cb.from_user
    subs = await get_active_subscriptions_for_ui(user.id)
    pending_promo = None
    pending_expires = None
    pending = await pending_db.get_active_pending_discount(user.id)
    if pending:
        promo = await promo_db.get_promo_by_id(pending["promo_id"])
        if promo:
            pending_promo = promo
            pending_expires = pending["expires_at"]
    greeting_template = await settings_db.get_start_greeting()
    announcement = await settings_db.get_start_announcement()
    if announcement:
        announcement = safe_html_fragment(announcement)
    refund_pending = await tickets_db.get_approved_refunds_pending_chargeback(user.id)
    pending_order = await get_resumable_pending_order(user.id)
    test_mode = await is_test_mode()
    return main_menu_text(
        user.first_name,
        user.username,
        subs,
        greeting_template=greeting_template,
        announcement=announcement,
        refund_pending_chargeback=bool(refund_pending),
        pending_discount_promo=pending_promo,
        pending_discount_expires_at=pending_expires,
        pending_payment_plan_name=pending_order.get("plan_name") if pending_order else None,
        test_mode=test_mode,
        design_id=design_id,
    )


async def _show_picker(cb: CallbackQuery, *, design_id: str | None = None) -> None:
    current = design_id or await get_menu_design_id()
    preview = await _preview_text(cb, current)
    await send_or_edit(cb, _picker_text(current=current, preview=preview), _design_kb(current))


@router.callback_query(F.data == "adm:debug:ui")
async def cb_debug_menu_design(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    await safe_cb_answer(cb)
    await _show_picker(cb)


@router.callback_query(F.data.startswith("adm:debug:ui:set:"))
async def cb_debug_menu_design_set(cb: CallbackQuery):
    if not is_debug_admin(cb.from_user.id):
        return
    requested = normalize_design_id((cb.data or "").rsplit(":", 1)[-1])
    if requested not in DESIGNS:
        await safe_cb_answer(cb, "Неизвестный макет", show_alert=True)
        return
    current = await set_menu_design_id(requested)
    toast = "как в релизе" if current == CLASSIC else design_label(current)
    await safe_cb_answer(cb, f"Дизайн: {toast}")
    await _show_picker(cb, design_id=current)

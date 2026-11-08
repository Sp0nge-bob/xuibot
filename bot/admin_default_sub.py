"""Админка: карточка дефолт-подписки (управление шаблонами пробных и платных клиентов)."""
from __future__ import annotations

from typing import Any
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from db import bot_settings as bot_settings_db
from services.limit_ip import apply_limit_ip_settings_on_primary
from services.xui import get_inbound_options
from .admin_auth import is_admin
from .admin_keyboards import admin_back_kb
from .states import AdminStates
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _render_default_sub_screen(
    target: CallbackQuery | Message,
    *,
    tab: str = "trial",
    notice: str = "",
) -> None:
    tab = "trial" if tab == "trial" else "paid"
    trial_enabled = await bot_settings_db.is_trial_enabled()
    trial_days = await bot_settings_db.get_trial_days()
    trial_traffic = await bot_settings_db.get_trial_traffic_gb()
    trial_ip = await bot_settings_db.get_trial_limit_ip()
    trial_hwid = await bot_settings_db.get_trial_limit_hwid()
    trial_inbounds = await bot_settings_db.get_trial_inbound_ids()

    paid_traffic = await bot_settings_db.get_paid_default_traffic_gb()
    paid_ip = await bot_settings_db.get_paid_limit_ip()
    paid_hwid = await bot_settings_db.get_paid_limit_hwid()
    paid_inbounds = await bot_settings_db.get_paid_inbound_ids()

    # Загружаем инбаунды
    try:
        all_inbounds = await get_inbound_options()
    except Exception:
        all_inbounds = []

    lines = [
        "📋 <b>Дефолт-подписка клиента (Шаблоны)</b>",
        "━━━━━━━━━━━━━━━━",
        "Настройки применяются для всех новых создаваемых подписок и клиентов соответствующего типа.\n",
    ]

    active_inbounds = trial_inbounds if tab == "trial" else paid_inbounds

    if tab == "trial":
        status_str = "✅ <b>Включена</b>" if trial_enabled else "⏸ <b>Отключена</b>"
        traffic_str = f"<b>{trial_traffic} ГБ</b>" if trial_traffic > 0 else "<b>без лимита</b>"
        ip_str = f"<b>{trial_ip}</b>" if trial_ip > 0 else "<b>без лимита (0)</b>"
        hwid_str = f"<b>{trial_hwid}</b>" if trial_hwid > 0 else "<b>без лимита (0)</b>"

        lines.extend([
            "<b>[ Вкладка: 🎁 Пробная подписка (Trial) ]</b>",
            f"• Статус выдачи: {status_str}",
            f"• Срок действия: <b>{trial_days} дн.</b>",
            f"• Лимит трафика: {traffic_str}",
            f"• Лимит одновременных IP: {ip_str}",
            f"• Лимит устройств (HWID): {hwid_str}",
            f"• Подключено инбаундов: <b>{len(active_inbounds)}</b> (ID: <code>{', '.join(str(x) for x in active_inbounds) or 'нет'}</code>)",
        ])
    else:
        traffic_str = f"<b>{paid_traffic} ГБ</b>" if paid_traffic > 0 else "<b>без лимита (0)</b>"
        ip_str = f"<b>{paid_ip}</b>" if paid_ip > 0 else "<b>без лимита (0)</b>"
        hwid_str = f"<b>{paid_hwid}</b>" if paid_hwid > 0 else "<b>без лимита (0)</b>"

    if tab == "paid":
        lines.extend([
            "<b>[ Вкладка: 💳 Платная подписка (Paid) ]</b>",
            "• Срок действия: <i>по выбранному тарифу</i>",
            f"• Дефолт трафика (если в тарифе 0): {traffic_str}",
            f"• Лимит одновременных IP: {ip_str}",
            f"• Лимит устройств (HWID): {hwid_str}",
            f"• Подключено инбаундов: <b>{len(active_inbounds)}</b> (ID: <code>{', '.join(str(x) for x in active_inbounds) or 'нет'}</code>)",
        ])

    lines.append("\n<b>📡 Подключаемые ноды / инбаунды:</b>")
    if not all_inbounds:
        lines.append("<i>Список инбаундов пуст или панель недоступна.</i>")
    else:
        for ib in all_inbounds:
            ib_id = int(ib.get("id") or 0)
            remark = ib.get("remark") or f"inbound #{ib_id}"
            proto = ib.get("protocol") or "vless"
            port = ib.get("port") or 443
            mark = "✅" if ib_id in active_inbounds else "⬜"
            lines.append(f"{mark} #{ib_id} <b>{remark}</b> (<code>{proto}:{port}</code>)")

    if notice:
        lines.extend(["", notice])

    text = "\n".join(lines)

    # Клавиатура
    kb_rows: list[list[InlineKeyboardButton]] = []

    # Табы
    trial_tab_label = "• 🎁 Пробная •" if tab == "trial" else "🎁 Пробная"
    paid_tab_label = "• 💳 Платная •" if tab == "paid" else "💳 Платная"
    kb_rows.append([
        InlineKeyboardButton(text=trial_tab_label, callback_data="adm:default_sub:tab:trial"),
        InlineKeyboardButton(text=paid_tab_label, callback_data="adm:default_sub:tab:paid"),
    ])

    if tab == "trial":
        toggle_label = "⏸ Отключить триал" if trial_enabled else "✅ Включить триал"
        kb_rows.append([
            InlineKeyboardButton(text=toggle_label, callback_data="adm:default_sub:trial_toggle"),
            InlineKeyboardButton(text=f"⏱ Срок: {trial_days} дн.", callback_data="adm:default_sub:edit:days:trial"),
        ])
        kb_rows.append([
            InlineKeyboardButton(text=f"📊 Трафик: {trial_traffic} ГБ", callback_data="adm:default_sub:edit:traffic:trial"),
            InlineKeyboardButton(text=f"📱 IP: {trial_ip}", callback_data="adm:default_sub:edit:ip:trial"),
            InlineKeyboardButton(text=f"🔒 HWID: {trial_hwid}", callback_data="adm:default_sub:edit:hwid:trial"),
        ])
    else:
        kb_rows.append([
            InlineKeyboardButton(text=f"📊 Дефолт трафик: {paid_traffic} ГБ", callback_data="adm:default_sub:edit:traffic:paid"),
        ])
        kb_rows.append([
            InlineKeyboardButton(text=f"📱 Лимит IP: {paid_ip}", callback_data="adm:default_sub:edit:ip:paid"),
            InlineKeyboardButton(text=f"🔒 Лимит HWID: {paid_hwid}", callback_data="adm:default_sub:edit:hwid:paid"),
        ])

    # Чекбоксы инбаундов
    if all_inbounds:
        for ib in all_inbounds:
            ib_id = int(ib.get("id") or 0)
            remark = ib.get("remark") or f"Inbound #{ib_id}"
            proto = ib.get("protocol") or "vless"
            mark = "✅" if ib_id in active_inbounds else "⬜"
            btn_text = f"{mark} #{ib_id} {remark} ({proto})"
            kb_rows.append([
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"adm:default_sub:toggle_ib:{tab}:{ib_id}",
                )
            ])

    # Кнопка применения лимитов к существующим клиентам
    kb_rows.append([
        InlineKeyboardButton(
            text="🔄 Применить лимиты к активным клиентам",
            callback_data=f"adm:default_sub:apply_limits:{tab}",
        )
    ])

    # Навигация
    kb_rows.append([
        InlineKeyboardButton(text="« VPN", callback_data="adm:hub:vpn"),
        InlineKeyboardButton(text="« Админ", callback_data="adm:menu"),
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:default_sub")
async def cb_default_sub_root(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _render_default_sub_screen(cb, tab="trial")


@router.callback_query(F.data.startswith("adm:default_sub:tab:"))
async def cb_default_sub_tab(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    tab = cb.data.split(":")[3]
    await safe_cb_answer(cb)
    await _render_default_sub_screen(cb, tab=tab)


@router.callback_query(F.data == "adm:default_sub:trial_toggle")
async def cb_default_sub_trial_toggle(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    current = await bot_settings_db.is_trial_enabled()
    new_state = not current
    await bot_settings_db.set_trial_enabled(new_state)
    await safe_cb_answer(cb, "Пробный период включён" if new_state else "Пробный период отключён")
    await _render_default_sub_screen(cb, tab="trial")


@router.callback_query(F.data.startswith("adm:default_sub:toggle_ib:"))
async def cb_default_sub_toggle_ib(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    tab = parts[3]
    ib_id = int(parts[4])

    if tab == "trial":
        current_ids = list(await bot_settings_db.get_trial_inbound_ids())
        if ib_id in current_ids:
            if len(current_ids) <= 1:
                await safe_cb_answer(cb, "Должен быть выбран хотя бы один инбаунд!", show_alert=True)
                return
            current_ids.remove(ib_id)
        else:
            current_ids.append(ib_id)
        await bot_settings_db.set_trial_inbound_ids(sorted(current_ids))
    else:
        current_ids = list(await bot_settings_db.get_paid_inbound_ids())
        if ib_id in current_ids:
            if len(current_ids) <= 1:
                await safe_cb_answer(cb, "Должен быть выбран хотя бы один инбаунд!", show_alert=True)
                return
            current_ids.remove(ib_id)
        else:
            current_ids.append(ib_id)
        await bot_settings_db.set_paid_inbound_ids(sorted(current_ids))

    await safe_cb_answer(cb)
    await _render_default_sub_screen(cb, tab=tab)


@router.callback_query(F.data.startswith("adm:default_sub:apply_limits:"))
async def cb_default_sub_apply_limits(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    tab = cb.data.split(":")[3]
    await safe_cb_answer(cb, "Применяем лимиты на панели…")
    stats = await apply_limit_ip_settings_on_primary(kind=tab)
    notice = (
        f"✅ <b>Лимиты IP применены ({tab}):</b>\n"
        f"Обновлено: <b>{stats['updated']}</b>, без изменений: <b>{stats['skipped']}</b>"
        + (f", не найдены: <b>{stats['missing']}</b>" if stats["missing"] else "")
        + (f", ошибок: <b>{stats['failed']}</b>" if stats["failed"] else "")
    )
    await _render_default_sub_screen(cb, tab=tab, notice=notice)


# --- Редактирование числовых параметров через ввод сообщения ---

@router.callback_query(F.data.startswith("adm:default_sub:edit:"))
async def cb_default_sub_edit(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    param = parts[3]
    kind = parts[4]

    await state.update_data(default_sub_param=param, default_sub_kind=kind)

    if param == "days":
        cur = await bot_settings_db.get_trial_days()
        await state.set_state(AdminStates.waiting_default_sub_days)
        prompt = (
            f"⏱ <b>Срок действия пробного периода</b>\n\n"
            f"Текущее значение: <b>{cur} дн.</b>\n\n"
            "Введите целое число дней (например, <code>3</code> или <code>7</code>):"
        )
    elif param == "traffic":
        cur = (
            await bot_settings_db.get_trial_traffic_gb()
            if kind == "trial"
            else await bot_settings_db.get_paid_default_traffic_gb()
        )
        await state.set_state(AdminStates.waiting_default_sub_traffic)
        prompt = (
            f"📊 <b>Лимит трафика ({kind})</b>\n\n"
            f"Текущее значение: <b>{cur} ГБ</b>\n\n"
            "Введите количество ГБ в месяц (<code>0</code> = без ограничений):"
        )
    elif param == "ip":
        cur = (
            await bot_settings_db.get_trial_limit_ip()
            if kind == "trial"
            else await bot_settings_db.get_paid_limit_ip()
        )
        await state.set_state(AdminStates.waiting_default_sub_limit_ip)
        prompt = (
            f"📱 <b>Лимит одновременных IP подключений ({kind})</b>\n\n"
            f"Текущее значение: <b>{cur}</b>\n\n"
            "Введите максимальное число IP (<code>0</code> = без ограничений):"
        )
    elif param == "hwid":
        cur = (
            await bot_settings_db.get_trial_limit_hwid()
            if kind == "trial"
            else await bot_settings_db.get_paid_limit_hwid()
        )
        await state.set_state(AdminStates.waiting_default_sub_limit_hwid)
        prompt = (
            f"🔒 <b>Лимит устройств (HWID) ({kind})</b>\n\n"
            f"Текущее значение: <b>{cur}</b>\n\n"
            "Введите максимальное число HWID устройств (<code>0</code> = без ограничений):"
        )
    else:
        await safe_cb_answer(cb, "Неизвестный параметр", show_alert=True)
        return

    await safe_cb_answer(cb)
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Отмена", callback_data=f"adm:default_sub:tab:{kind}")],
    ])
    await send_or_edit(cb, prompt, cancel_kb)


@router.message(AdminStates.waiting_default_sub_days)
async def msg_default_sub_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) < 1:
        await message.answer("❌ Введите целое число дней больше 0 (например, 3)")
        return
    val = int(raw)
    await bot_settings_db.set_trial_days(val)
    await state.clear()
    await _render_default_sub_screen(message, tab="trial", notice=f"✅ Срок пробной подписки установлен: <b>{val} дн.</b>")


@router.message(AdminStates.waiting_default_sub_traffic)
async def msg_default_sub_traffic(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    kind = data.get("default_sub_kind") or "trial"
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ Введите целое число ГБ (0 = безлимит):")
        return
    val = int(raw)
    if kind == "trial":
        await bot_settings_db.set_trial_traffic_gb(val)
    else:
        await bot_settings_db.set_paid_default_traffic_gb(val)
    await state.clear()
    await _render_default_sub_screen(message, tab=kind, notice=f"✅ Лимит трафика ({kind}) установлен: <b>{val} ГБ</b>")


@router.message(AdminStates.waiting_default_sub_limit_ip)
async def msg_default_sub_limit_ip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    kind = data.get("default_sub_kind") or "trial"
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ Введите целое число IP (0 = безлимит):")
        return
    val = int(raw)
    if kind == "trial":
        await bot_settings_db.set_trial_limit_ip(val)
    else:
        await bot_settings_db.set_paid_limit_ip(val)
    await state.clear()
    await _render_default_sub_screen(message, tab=kind, notice=f"✅ Лимит IP ({kind}) установлен: <b>{val}</b>")


@router.message(AdminStates.waiting_default_sub_limit_hwid)
async def msg_default_sub_limit_hwid(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    kind = data.get("default_sub_kind") or "trial"
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ Введите целое число устройств HWID (0 = безлимит):")
        return
    val = int(raw)
    if kind == "trial":
        await bot_settings_db.set_trial_limit_hwid(val)
    else:
        await bot_settings_db.set_paid_limit_hwid(val)
    await state.clear()
    await _render_default_sub_screen(message, tab=kind, notice=f"✅ Лимит HWID ({kind}) установлен: <b>{val}</b>")

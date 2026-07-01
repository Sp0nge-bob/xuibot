"""Hub-навигация админ-панели: корень → раздел → существующие adm:* экраны."""
from __future__ import annotations

from typing import TypedDict

from aiogram import Router, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config.settings import settings
from .admin_auth import is_admin
from .messages import admin_hub_section_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


class HubDef(TypedDict):
    root_label: str
    title: str
    description: str
    items: list[tuple[str, str]]


ADMIN_HUBS: dict[str, HubDef] = {
    "overview": {
        "root_label": "📊 Обзор",
        "title": "📊 Обзор",
        "description": "Сводка по боту и проверка инфраструктуры.",
        "items": [
            ("📊 Статистика", "adm:stats"),
            ("🔍 Диагностика", "adm:diagnostics"),
        ],
    },
    "billing": {
        "root_label": "💰 Монетизация",
        "title": "💰 Монетизация",
        "description": "Тарифы, способы оплаты и промокоды.",
        "items": [
            ("💰 Тарифы", "adm:plans"),
            ("💳 Оплата", "adm:payments"),
            ("🎟 Промокоды", "adm:promos"),
        ],
    },
    "clients": {
        "root_label": "👥 Клиенты",
        "title": "👥 Клиенты",
        "description": "Подключённые пользователи и обращения в поддержку.",
        "items": [
            ("👥 Клиенты", "adm:users"),
            ("🎫 Тикеты", "adm:tickets"),
        ],
    },
    "vpn": {
        "root_label": "🖧 VPN",
        "title": "🖧 VPN и панели",
        "description": "Ноды 3x-ui, инбаунды, доступность и лимиты подключений.",
        "items": [
            ("🖧 Ноды", "adm:nodes"),
            ("📡 Inbounds", "adm:inbounds"),
            ("🌐 Доступность инбаундов", "adm:server_status"),
            ("📱 Лимит IP", "adm:limit_ip"),
            ("🔐 Happ", "adm:happ_crypto"),
        ],
    },
    "content": {
        "root_label": "📝 Контент",
        "title": "📝 Контент бота",
        "description": "FAQ, текст /start и юридические документы.",
        "items": [
            ("❓ FAQ", "adm:faq"),
            ("📢 /start", "adm:start_text"),
            ("📄 Документы", "adm:legal"),
        ],
    },
    "system": {
        "root_label": "⚙️ Система",
        "title": "⚙️ Система",
        "description": "Резервные копии и служебные инструменты.",
        "items": [
            ("💾 Бэкап", "adm:backup"),
        ],
    },
}

_HUB_ROOT_ORDER = ("overview", "billing", "clients", "vpn", "content", "system")


def _system_hub_items() -> list[tuple[str, str]]:
    items = list(ADMIN_HUBS["system"]["items"])
    if settings.ALLOW_DEBUG_ADMIN:
        items.append(("🧪 Отладка", "adm:debug"))
    return items


def admin_hub_root_kb(*, pending_tickets: int = 0) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []

    for hub_id in _HUB_ROOT_ORDER:
        hub = ADMIN_HUBS[hub_id]
        label = hub["root_label"]
        if hub_id == "clients" and pending_tickets > 0:
            label = f"{label} · {pending_tickets}"
        pair.append(InlineKeyboardButton(
            text=label,
            callback_data=f"adm:hub:{hub_id}",
        ))
        if len(pair) == 2:
            rows.append(pair)
            pair = []

    if pair:
        rows.append(pair)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_hub_section_kb(hub_id: str) -> InlineKeyboardMarkup:
    hub = ADMIN_HUBS.get(hub_id)
    if not hub:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« К админ-панели", callback_data="adm:menu")],
        ])

    items = _system_hub_items() if hub_id == "system" else hub["items"]
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []

    for label, callback in items:
        pair.append(InlineKeyboardButton(text=label, callback_data=callback))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([InlineKeyboardButton(text="« К админ-панели", callback_data="adm:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_kb(*, pending_tickets: int = 0) -> InlineKeyboardMarkup:
    """Корневая клавиатура админ-панели (hub-меню)."""
    return admin_hub_root_kb(pending_tickets=pending_tickets)


@router.callback_query(F.data.startswith("adm:hub:"))
async def cb_admin_hub_section(cb):
    if not is_admin(cb.from_user.id):
        return

    hub_id = cb.data.split(":", 2)[2]
    hub = ADMIN_HUBS.get(hub_id)
    if not hub:
        await safe_cb_answer(cb, "Раздел не найден", show_alert=True)
        return

    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_hub_section_text(
            title=hub["title"],
            description=hub["description"],
        ),
        admin_hub_section_kb(hub_id),
    )
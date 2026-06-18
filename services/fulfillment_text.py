"""Тексты сообщений после успешной выдачи подписки."""
from __future__ import annotations

from ui.theme import screen

# Лимит Telegram для caption у фото
TELEGRAM_PHOTO_CAPTION_MAX = 1024


def sub_link_needs_separate_message(sub_link: str | None) -> bool:
    """happ://crypt* не влезает в caption вместе с остальным текстом."""
    if not sub_link:
        return False
    if sub_link.startswith("happ://crypt"):
        return True
    return len(sub_link) > 350


def sub_link_caption_lines(sub_link: str | None) -> list[str]:
    if not sub_link:
        return []
    if sub_link_needs_separate_message(sub_link):
        return ["", "🔗 <b>Ссылка на подписку</b> — в следующем сообщении 👇"]
    return ["", "🔗 <b>Ссылка на подписку:</b>", f"<code>{sub_link}</code>"]


def sub_link_standalone_message(sub_link: str | None) -> str | None:
    if not sub_link or not sub_link_needs_separate_message(sub_link):
        return None
    return (
        "🔗 <b>Скопируйте ссылку</b> (или отсканируйте QR выше):\n\n"
        f"<code>{sub_link}</code>"
    )


def panel_sync_notice_text(inbound_count: int) -> str:
    return (
        "⏳ <i>Синхронизация на серверах может занять пару минут. "
        "Обновите подписку через 2 минуты, чтобы увидеть все серверы. "
        f"Серверов в подписке: <b>{inbound_count}</b></i>"
    )


def qr_and_sync_footer(inbound_count: int) -> str:
    """Общий блок под QR: подсказка + синхронизация (платная и пробная подписка)."""
    return "\n".join([
        "",
        "Скопируйте ссылку или отсканируйте QR-код ниже.",
        "",
        panel_sync_notice_text(inbound_count),
    ])


def happ_setup_text() -> str:
    return screen(
        "📲 <b>Как подключить VPN (Happ)</b>",
        "Для подключения выполните шаги ниже.\n"
        "На скриншотах отмечены нужные кнопки 👇",
        "\n".join([
            "1️⃣ Скопируйте <b>ссылку на подписку</b> из сообщения выше",
            "",
            "2️⃣ Установите приложение <b>Happ</b>\n"
            "   • Android / iOS — магазин приложений\n"
            "   • Windows — с официального сайта Happ",
            "",
            "3️⃣ Запустите Happ",
            "",
            "4️⃣ Нажмите <b>«+»</b> → <b>«Вставить из буфера обмена»</b>\n"
            "   или отсканируйте присланный <b>QR-код</b>",
            "",
            "5️⃣ Если VPN не работает — обновите настройки:\n"
            "   🔴 кнопка под <b>красной стрелкой</b> на скриншоте",
            "",
            "   Проверка соединения на всех серверах:\n"
            "   🟡 кнопка под <b>жёлтой стрелкой</b> на скриншоте",
        ]),
    )
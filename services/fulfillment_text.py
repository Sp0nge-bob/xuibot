"""Тексты сообщений после успешной выдачи подписки."""
from __future__ import annotations

from ui.theme import screen

# Лимит Telegram для caption у фото
TELEGRAM_PHOTO_CAPTION_MAX = 1024


def sub_link_needs_separate_message(sub_link: str | None) -> bool:
    """happ://crypt* и incy://crypt* выносятся в отдельное сообщение для удобного копирования."""
    if not sub_link:
        return False
    if sub_link.startswith(("happ://crypt", "incy://crypt")):
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
        "Выберите удобный клиент ниже или нажмите «🔗 Ссылка и QR».",
        "",
        panel_sync_notice_text(inbound_count),
    ])


def happ_setup_body() -> str:
    """Пошаговая инструкция для клиента Happ со скриншотами."""
    return "\n".join([
        "Для подключения через <b>Happ</b> выполните шаги ниже.\n"
        "На скриншотах отмечены нужные кнопки 👇",
        "",
        "1️⃣ Нажмите кнопку <b>«📱 Добавить в Happ»</b> в карточке подписки "
        "или скопируйте ключ Happ через <b>«🔗 Ссылка и QR»</b>",
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
        "5️⃣ Если подключение не работает — обновите настройки:\n"
        "   🔴 кнопка под <b>красной стрелкой</b> на скриншоте",
        "",
        "   Проверка соединения на всех серверах:\n"
        "   🟡 кнопка под <b>жёлтой стрелкой</b> на скриншоте",
    ])


def incy_setup_body() -> str:
    """Пошаговая инструкция для клиента INCY (доступен в App Store РФ без смены региона)."""
    return "\n".join([
        "<b>INCY</b> — современный клиент для всех платформ. "
        "Доступен в российском <b>App Store без смены региона Apple ID</b>!\n",
        "1️⃣ <b>Установите приложение INCY:</b>",
        '   • iOS / macOS (App Store РФ): <a href="https://apps.apple.com/us/app/incy/id6756943388">Скачать в App Store</a>',
        '   • Android: <a href="https://play.google.com/store/apps/details?id=com.incy.vpn">Google Play</a>',
        '   • Windows: <a href="https://incy.cc/downloads/incy-windows-x64-installer.exe">Установщик Windows (.exe)</a>',
        '   • macOS (DMG): <a href="https://incy.cc/downloads/incy-macos-universal.dmg">Скачать .dmg</a>',
        '   • Linux: <a href="https://incy.cc/downloads/incy-linux-x86_64.AppImage">Скачать .AppImage</a>',
        '   • Все платформы: <a href="https://incy.cc">incy.cc</a>',
        "",
        "2️⃣ <b>Добавьте подписку в 1 клик:</b>",
        "   Нажмите кнопку <b>«🛡 Добавить в INCY»</b> в карточке вашей подписки — "
        "приложение откроется и предложит подтвердить импорт.",
        "",
        "3️⃣ <b>Или добавьте вручную по ключу / QR-коду:</b>",
        "   Нажмите <b>«🔗 Ссылка и QR»</b> → выберите <b>«🛡 INCY»</b>, "
        "скопируйте защищённый ключ <code>incy://crypt1/...</code> (или отсканируйте QR-код) "
        "и вставьте его в приложении INCY.",
    ])


def activation_setup_body() -> str:
    """Обзорная инструкция по выбору клиента (Happ или INCY) — для FAQ и кнопки подключения."""
    return "\n".join([
        "Выберите удобное приложение для подключения вашей подписки:\n",
        "📱 <b>Вариант 1: Happ</b>",
        "Основной клиент для Android, iOS, Windows и macOS. "
        "Поддерживает быстрое добавление в 1 клик и наглядную проверку пинга серверов.",
        "",
        "🛡 <b>Вариант 2: INCY (без смены региона App Store в РФ)</b>",
        "Отличная альтернатива, если вам не подходит Happ или вы используете iPhone "
        "с российским аккаунтом App Store (устанавливается напрямую без смены региона).",
        "",
        "👇 <b>Выберите клиент ниже, чтобы открыть подробную инструкцию:</b>",
    ])


def happ_setup_text() -> str:
    return screen(
        "📱 <b>Инструкция по подключению: Happ</b>",
        happ_setup_body(),
    )


def incy_setup_text() -> str:
    return screen(
        "🛡 <b>Инструкция по подключению: INCY</b>",
        incy_setup_body(),
    )


def activation_setup_text() -> str:
    return screen(
        "📲 <b>Как подключить подписку</b>",
        activation_setup_body(),
    )
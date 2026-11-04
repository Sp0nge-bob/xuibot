<p align="center">
  <img src="https://cdn.simpleicons.org/telegram/26A5E4" width="112" height="112" alt="Логотип Telegram">
</p>

<h1 align="center">VPN Shop Bot</h1>

<p align="center">
  Telegram-бот для продажи VPN-подписок с оплатой через Platega<br>
  и автоматической выдачей доступа через 3x-ui.
</p>

<p align="center">
  <a href="https://github.com/Sp0nge-bob/xuibot/releases"><img src="https://img.shields.io/badge/version-1.5.0-2ea44f" alt="Версия 1.5.0"></a>
  <img src="https://img.shields.io/badge/Python-3.11%E2%80%933.14-3776AB?logo=python&logoColor=white" alt="Python 3.11–3.14">
  <a href="docs/README.md"><img src="https://img.shields.io/badge/docs-руководства-blue" alt="Документация"></a>
  <img src="https://img.shields.io/badge/Telegram-bot-26A5E4?logo=telegram&logoColor=white" alt="Telegram-бот">
</p>

<p align="center"><a href="docs/README.md">Документация</a> · <a href="SECURITY.md">Безопасность</a></p>

---

Поддерживаются тарифы, промокоды, пробный период, реферальная программа, FAQ, тикеты, возвраты, несколько VPN-нод и ссылки для Happ. Для администрирования доступны `/admin`, диагностика и резервное копирование.

**Python:** 3.11–3.14 · **Развёртывание:** Ubuntu/Debian VPS

> [!IMPORTANT]
> Храните токены и пароли только в `.env`. Не публикуйте этот файл и не добавляйте его в Git. См. [правила безопасности](SECURITY.md).

## Установка на VPS

На чистом Ubuntu/Debian сервере запустите мастер установки от имени администратора:

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh | sudo bash
```

Мастер установит приложение и службы, запросит Telegram-токен и параметры 3x-ui, а также предложит настроить Platega. После установки команда `vpnplategabot` откроет меню управления:

```bash
vpnplategabot
sudo vpnplategabot update
```

Если платежи будут приниматься через Platega, настройте HTTPS webhook: URL из `.env` нужно указать в кабинете Platega и проксировать через nginx. Подробности — в разделах [установки](docs/installation.md) и [настройки Platega](docs/platega.md).

## Быстрый запуск вручную

Для установки без мастера используйте bootstrap-скрипт:

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh | sudo bash -s -- /opt/vpn-bot
sudo nano /opt/vpn-bot/.env
sudo bash /opt/vpn-bot/deploy/vpn-bot-ctl.sh
```

Для локального запуска из клонированного репозитория:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python run_all.py
```

Заполните `.env` перед запуском. Описание параметров — в [конфигурации](docs/configuration.md); локальный сценарий разработки — в [руководстве разработчика](docs/development.md).

## Документация

Начните с [оглавления документации](docs/README.md). Там есть пошаговый маршрут запуска, руководства по интеграциям и раздел с устранением неполадок.

| Задача | Раздел |
| --- | --- |
| Установить и обновить бота | [Установка](docs/installation.md) · [Деплой](docs/deployment.md) |
| Заполнить `.env` | [Конфигурация](docs/configuration.md) |
| Подключить панель VPN | [3x-ui](docs/xui.md) |
| Настроить оплату | [Platega](docs/platega.md) |
| Управлять клиентами и подписками | [Админка](docs/admin.md) · [Подписки](docs/subscriptions.md) |
| Найти причину сбоя | [Решение проблем](docs/troubleshooting.md) |

## Структура проекта

| Каталог или файл | Назначение |
| --- | --- |
| `app.py` | FastAPI-приложение и webhook Platega |
| `run_bot.py` | Telegram-бот и планировщик |
| `run_all.py` | Запуск webhook и бота одной командой |
| `bot/` | Обработчики Telegram, меню и админка |
| `services/` | Интеграции с Platega и 3x-ui, выдача доступа и диагностика |
| `db/` | SQLite и операции с данными |
| `deploy/` | Установка, systemd и команды управления |
| `docs/` | Руководства и справочные материалы |

## Перед первым запуском

- Укажите Telegram-токен и ID администраторов.
- Настройте доступ к основной панели 3x-ui и выберите inbounds.
- Для реальных платежей задайте реквизиты Platega, HTTPS `PUBLIC_WEBHOOK_URL` и выключите `TEST_MODE`.
- Проверьте настройки и подключения в `/admin` → **Обзор** → **Диагностика**.

Пошаговый production-чеклист находится в [руководстве по деплою](docs/deployment.md#чеклист).

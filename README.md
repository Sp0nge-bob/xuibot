# VPN Shop Bot (Platega + 3x-ui)

Telegram-бот для продажи VPN-подписок: оплата через **Platega**, выдача ключей через **3x-ui** (главная панель + Nodes).

**Возможности:** тарифы, 5 способов оплаты, промокоды, пробный период, тикеты поддержки, возвраты, мульти-ноды, админка `/admin`.

> **Секреты:** файл `.env` не должен попадать в git. См. [SECURITY.md](SECURITY.md).

---

## Быстрый старт (продакшен)

```bash
# Склонируйте репозиторий в каталог на сервере
cd /opt/vpn-bot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -U pip && pip install -e .
cp .env.example .env && nano .env
```

**Обязательно в `.env`:**

| Переменная | Значение |
|------------|----------|
| `TEST_MODE` | `false` |
| `START_BOT_IN_WEBAPP` | `false` |
| `PUBLIC_WEBHOOK_URL` | HTTPS URL + `/platega-webhook` |
| `ALLOW_DEBUG_ADMIN` | `false` |

**Запуск одной командой** (webhook + Telegram, два процесса):

```bash
python run_all.py
```

Или в двух терминалах / через systemd:

```bash
python app.py       # webhook Platega + очередь выдачи
python run_bot.py   # Telegram polling + планировщик
```

Для отладки в одном процессе: `START_BOT_IN_WEBAPP=true` в `.env`, затем `python app.py`.

Проверка webhook: `curl https://your-domain.com/health` → `{"status":"ok"}`

---

## Документация

**[docs/README.md](docs/README.md)** — оглавление и навигация по разделам.

| Раздел | Описание |
|--------|----------|
| [Архитектура](docs/architecture.md) | Два процесса, схема работы |
| [Установка](docs/installation.md) | Python, venv, systemd |
| [Конфигурация](docs/configuration.md) | Переменные `.env` |
| [Деплой](docs/deployment.md) | Чеклист прода, nginx |
| [3x-ui](docs/xui.md) | Панель, подписка, утилиты |
| [Platega](docs/platega.md) | Платежи и webhook |
| [Админка](docs/admin.md) | Команда `/admin` |
| [Подписки](docs/subscriptions.md) | Истечение, реактивация, возвраты |
| [Разработка](docs/development.md) | TEST_MODE, логи, скрипты |
| [Troubleshooting](docs/troubleshooting.md) | Решение типичных проблем |

---

## Структура

| Путь | Назначение |
|------|------------|
| `run_all.py` | Запуск webhook + Telegram одной командой |
| `app.py` | FastAPI: webhook Platega, очередь fulfillment |
| `run_bot.py` | Telegram-бот (polling) |
| `bot/` | aiogram: меню, админка, тикеты |
| `services/` | Platega, 3x-ui, синхронизация нод |
| `db/` | SQLite |
| `ui/` | тексты и дизайн-система |
| `scripts/` | утилиты (`list_inbounds.py`, `dedupe_nodes.py`) |
| `scripts/dev/` | скрипты разработки (не для прода) |
| `deploy/systemd/` | примеры unit-файлов для systemd |

**Не в репозитории** (только локально): `.env`, `data/`, `.venv/`, `mcps/`.

---

## Перед публикацией на GitHub

1. Убедитесь, что `.env` не отслеживается git (`git ls-files .env` — пусто)
2. Ротируйте все ключи, если `.env` когда-либо коммитился
3. Очистите историю git от секретов, если они уже были в remote
4. Подробнее — [SECURITY.md](SECURITY.md)

---

## Чеклист перед запуском

1. `TEST_MODE=false`, реальные `PLATEGA_*`
2. Callback URL в ЛК Platega = `PUBLIC_WEBHOOK_URL`
3. `/admin` → способы оплаты, цены, ноды, inbounds
4. Тестовый платёж → ключ выдан → клиент в 3x-ui
5. `LOG_LEVEL=INFO` (health нод и webhook body — только в DEBUG)
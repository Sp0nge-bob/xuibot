# VPN Shop Bot (Platega + 3x-ui)

Telegram-бот для продажи VPN-подписок: оплата через **Platega**, выдача ключей через **3x-ui** (главная панель + ноды).

**Возможности:** тарифы, 5 способов оплаты, промокоды, пробный период, реферальная программа, FAQ, тикеты и возвраты, мульти-ноды, Happ-шифрование ссылок, hub-админка с диагностикой и lockdown.

**Версия:** [v1.0.0](https://github.com/Sp0nge-bob/xuibot/releases) · **Python:** 3.11–3.14

> **Секреты:** `.env` не должен попадать в git. См. [SECURITY.md](SECURITY.md).

---

## Быстрый старт (продакшен)

```bash
# без git на сервере — одна команда:
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
  | sudo bash -s -- /opt/vpn-bot
sudo nano /opt/vpn-bot/.env    # из .env.example
sudo bash /opt/vpn-bot/deploy/vpn-bot-ctl.sh   # пункт 1 → установка
```

Или вручную:

```bash
cd /opt/vpn-bot
python3.11 -m venv .venv && source .venv/bin/activate   # или python3.12…3.14
pip install -U pip && pip install -e .
cp .env.example .env && nano .env
```

**Обязательно в `.env`:**

| Переменная | Значение |
|------------|----------|
| `TEST_MODE` | `false` |
| `START_BOT_IN_WEBAPP` | `false` |
| `PUBLIC_WEBHOOK_URL` | HTTPS + `/platega-webhook` |
| `ALLOW_DEBUG_ADMIN` | `false` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` (рекомендуется в проде) |

**Запуск:**

```bash
python run_all.py          # webhook + Telegram
# или: python app.py + python run_bot.py
# systemd: sudo bash deploy/vpn-bot-ctl.sh → 1
```

Проверка: `curl https://your-domain.com/health` → `{"status":"ok"}`

**Обновление на VPS:**

```bash
sudo bash deploy/vpn-bot-ctl.sh update           # последний Release (stable)
sudo bash deploy/vpn-bot-ctl.sh update --edge    # последний коммит main
```

Релизные заметки: [docs/RELEASE_v1.0.0.md](docs/RELEASE_v1.0.0.md).

---

## Документация

**[docs/README.md](docs/README.md)** — оглавление.

| Раздел | Описание |
|--------|----------|
| [Архитектура](docs/architecture.md) | Два процесса, lockdown, планировщик |
| [Установка](docs/installation.md) | Python **3.11–3.14**, venv, `vpn-bot-ctl.sh` |
| [Конфигурация](docs/configuration.md) | Переменные `.env`, Redis, рефералы |
| [Деплой](docs/deployment.md) | Чеклист прода, nginx, обновление |
| [Системные требования](docs/requirements.md) | VPS по нагрузке |
| [3x-ui](docs/xui.md) | Панель, подписка, ноды |
| [Platega](docs/platega.md) | Платежи и webhook |
| [Админка](docs/admin.md) | Hub `/admin`, диагностика, отладка |
| [Подписки](docs/subscriptions.md) | Истечение, рефералы, возвраты |
| [Разработка](docs/development.md) | TEST_MODE, логи, скрипты |
| [Troubleshooting](docs/troubleshooting.md) | Типичные проблемы |
| [Redis — план](docs/redis-migration-plan.md) | FSM и сессии |
| [PostgreSQL — план](docs/postgresql-migration-plan.md) | Опционально на будущее |

---

## Структура

| Путь | Назначение |
|------|------------|
| `run_all.py` | Webhook + Telegram одной командой |
| `app.py` | FastAPI: webhook, очередь fulfillment |
| `run_bot.py` | Telegram polling + планировщик |
| `bot/` | aiogram: меню, админка, тикеты, middleware |
| `services/` | Platega, 3x-ui, lockdown, диагностика |
| `db/` | SQLite (заказы, подписки, настройки) |
| `ui/` | Тексты и `screen()` |
| `deploy/` | `vpn-bot-ctl.sh`, systemd |
| `scripts/dev/` | Тесты и утилиты разработки |

**Локально только:** `.env`, `data/`, `.venv/`.

---

## Чеклист перед запуском

1. `TEST_MODE=false`, реальные `PLATEGA_*`
2. Callback URL в Platega = `PUBLIC_WEBHOOK_URL`
3. `/admin` → оплата, тарифы, ноды, inbounds
4. Тестовый платёж → ключ → клиент в 3x-ui
5. `/admin` → **Диагностика** — зелёная сводка
6. `LOG_LEVEL=INFO` в проде
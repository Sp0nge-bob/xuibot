[← Документация](README.md) · [Архитектура](architecture.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Установка

## Одной командой (рекомендуется)

На Ubuntu/Debian VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh \
  | sudo bash
```

Каталог по умолчанию: `/opt/vpn-bot` (можно передать аргументом: `… | sudo bash -s -- /opt/vpn-bot`).

**Что делает мастер** (`deploy/install.sh`):

1. Ставит пакеты (`curl`, `python3`, …) и скачивает **последний GitHub Release**
2. Спрашивает `BOT_TOKEN` и **сразу проверяет** его через `https://api.telegram.org/bot…/getMe`
3. Спрашивает `BOT_ADMINS`, Primary **3x-ui** (`XUI_HOST` + token или логин/пароль)
4. Platega — опционально; иначе включает `TEST_MODE=true`
5. Запускает полный install: Redis, venv, systemd, старт служб  
6. Ставит команду **`vpnplategabot`** → `/usr/local/bin/vpnplategabot` (меню ctl, как `x-ui`)

```bash
vpnplategabot                 # интерактивное меню
sudo vpnplategabot update     # stable-релиз
```

Повторный запуск не затирает `data/` / `.venv/`; про существующий `.env` спросит отдельно.

**Slim на VPS:** при install/update **не копируются** `docs/`, `report/`, `scripts/dev/`, корневые `*.md` (документация остаётся на GitHub). Нужны только код, `deploy/`, `assets/`, `templates/`.

### После установки: webhook Platega

Если Platega настроена в мастере (`TEST_MODE=false`), в конце скрипт **печатает `PUBLIC_WEBHOOK_URL`** из `.env`. Этот адрес:

1. Нужен в **личном кабинете Platega** как Callback / Webhook URL — иначе платежи не подтвердятся.
2. Нужно **добавить в nginx** (HTTPS) и проксировать на `http://127.0.0.1:8080` — см. [Деплой → nginx](deployment.md#nginx-фрагмент) и [Platega](platega.md).

При `TEST_MODE=true` боевой webhook не обязателен; для прода задайте URL позже в `.env`.

---

## Требования

**Python 3.11–3.14** (`requires-python` в `pyproject.toml`: `>=3.11,<3.15`), доступ к главной панели 3x-ui, HTTPS-домен для webhook (если не TEST_MODE).

Скрипт деплоя (`deploy/lib/python.sh`) предпочитает более новую версию (`python3.14` → … → `python3.11`).

## Ручная установка (venv)

```bash
cd /opt/vpn-bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

Заполните `.env` (см. [Конфигурация](configuration.md)), затем:

```bash
python run_all.py          # webhook + Telegram
# или: python app.py + python run_bot.py
```

Для отладки в одном процессе: `START_BOT_IN_WEBAPP=true`, затем `python app.py`.

## systemd (`deploy/vpn-bot-ctl.sh`)

Интерактивное меню:

```bash
sudo bash deploy/vpn-bot-ctl.sh
```

| Пункт | Действие |
|-------|----------|
| **1** | Установить / починить: venv, pip, redis-server, `REDIS_URL`, права, unit-файлы |
| **2** | **Stable:** обновить до последнего **GitHub Release** + рестарт |
| **3** | **Edge:** обновить до последнего коммита `main` + рестарт |
| **4** | Быстрый перезапуск служб |
| **5** | Статус служб + Redis |
| **6** | Логи `tail -f` |
| **7** | Остановить службы |
| **8** | Удалить unit-файлы (службы) |
| **9** | **Снести бота полностью** — units + каталог + user `vpnbot` + sudoers; выбор **с Redis / без Redis**; подтверждение: `DELETE` |

**Первая установка** (без git на сервере):

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
  | sudo bash -s -- /opt/vpn-bot
# заполните /opt/vpn-bot/.env
sudo bash /opt/vpn-bot/deploy/vpn-bot-ctl.sh   # пункт 1
```

**Обычное обновление (прод):** пункт **2** или:

```bash
sudo bash deploy/vpn-bot-ctl.sh update              # последний Release
sudo bash deploy/vpn-bot-ctl.sh update --edge       # последний коммит
```

Локальный `.git` **не нужен**. Сохраняются `.env`, `data/`, `.venv/`.

Меню ctl — стиль Charm/gum (цвета ANSI). Отключить: `NO_COLOR=1`. На locale без UTF-8 рамки автоматически ASCII (`+--+`), без кракозябр.

**Если изменился `pyproject.toml` / новые зависимости:** после `update` при необходимости пункт **1**.

**Redis:** пункт 1 на Debian/Ubuntu ставит `redis-server` и добавляет `REDIS_URL=redis://127.0.0.1:6379/0`, если строки нет в `.env`.

**Полный снос (пункт 9 / `purge`):** перед `DELETE` спрашивает, удалять ли Redis. По умолчанию Redis **оставляется** (на хосте могут быть другие сервисы). Вариант «с Redis» делает `stop/disable` и снимает пакет `redis-server`.

```bash
sudo vpnplategabot                    # меню → 9
sudo bash deploy/vpn-bot-ctl.sh purge --without-redis
sudo bash deploy/vpn-bot-ctl.sh purge --with-redis
```

Алиас: `sudo bash deploy/install-systemd.sh` (то же меню).

Неинтерактивно:

```bash
sudo bash deploy/vpn-bot-ctl.sh install   # полная установка
sudo bash deploy/vpn-bot-ctl.sh update    # git pull + restart
sudo bash deploy/vpn-bot-ctl.sh restart # только restart
```

Unit-шаблоны: [`deploy/systemd/*.template`](../deploy/systemd/).

---

**Назад:** [← Архитектура](architecture.md) · **Далее:** [Конфигурация →](configuration.md)
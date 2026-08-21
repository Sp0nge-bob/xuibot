[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md)

---

# Troubleshooting

Первый шаг в проде: `/admin` → **Обзор** → **Диагностика** (сводка и разделы с рекомендациями).

## Бот не отвечает в Telegram

- Запущен ли процесс? (`systemctl status vpn-bot-telegram` или `python run_bot.py`)
- Логи: `Подключён @username`, `Polling started`
- Верный `BOT_TOKEN`?
- **Lockdown:** `/admin` → **Отладка** → блокировка; или ★ Primary offline (автоблокировка)
- **Polling lock:** диагностика → «Процессы»; мёртвый PID — удалить `data/.polling.lock`, restart

## Webhook не приходит

- `curl` на `PUBLIC_WEBHOOK_URL` и `/health`
- Callback URL в Platega = `PUBLIC_WEBHOOK_URL`
- nginx → `WEBHOOK_PORT`
- `TEST_MODE=false` для реальных платежей
- Диагностика → **Webhook**: local/public health, Platega API

## Оплата прошла, ключа нет

- Логи `app.py`: `Platega callback: tx=... status=CONFIRMED`
- Очередь выдачи: диагностика → воркеры fulfillment
- Ноды online: диагностика → **VPN**
- `XUI_HOST` без `/panel/`

## Бот «на обслуживании» / оплата приостановлена

| Сообщение | Причина |
|-----------|---------|
| Техобслуживание | Ручная блокировка (полная) |
| Сервис недоступен | ★ Primary недоступна |
| Оплата приостановлена | Draining — ждут завершения PENDING |

Поддержка и тикеты работают. Снять ручную блокировку: `/admin` → **Отладка** → **Блокировка**.

## ★ Primary недоступна

- Диагностика → VPN / сводка
- `/admin` → **Ноды** → «Проверить»
- URL без `/panel/`, актуальный токен
- `curl -k` на host панели с VPS
- При Primary down или массовом fail (≥2 нод) бот сам гоняет **автодиагностику** (DNS/TCP/HTTP/API) и шлёт отчёт в ЛС `BOT_ADMINS` (один раз на инцидент; `PANEL_OUTAGE_DIAG_*` в `.env`)

## Python / venv

- Поддержка: **3.11–3.14**. Проверка: `.venv/bin/python -V` и `python scripts/dev/smoke_python314.py`.
- После смены major Python на VPS: пункт **1** `vpn-bot-ctl.sh` (пересоздаст venv) или вручную `rm -rf .venv && python3.14 -m venv .venv && pip install -e .`.

## Обновление без git / архив GitHub

Пункт **2** (`vpn-bot-ctl.sh update`) больше **не требует** локальный `.git`:

1. Есть `.git` → `git pull`
2. Нет `.git` → скачивается tarball **последнего коммита** ветки `main` с GitHub и накладывается на каталог
3. Сохраняются: `.env`, `data/`, `.venv/`, `deploy/state.env`
4. SHA пишется в `.deploy_revision` (повторный update с тем же SHA — no-op)

```bash
cd /opt/vpn-bot
sudo bash deploy/vpn-bot-ctl.sh update
# или сразу архив:
sudo UPDATE_METHOD=archive bash deploy/vpn-bot-ctl.sh update
```

Нужны `curl` (или `wget`), `python3`, желательно `rsync`. Сеть до `api.github.com` и `github.com`.

Форк: `GIT_REMOTE=https://github.com/ORG/REPO.git GIT_BRANCH=main`.

Если ctl ещё **старый** (ошибка «Не git-репозиторий») — один раз обновите `deploy/` вручную или скачайте свежий release/zip поверх кода, затем снова пункт **2**.

## Ошибка 3x-ui / таймаут

- Осторожно с `XUI_PANEL_CONCURRENCY`
- `LOG_LEVEL=DEBUG` для API
- Вторичная нода down — пользователи видят предупреждение; проверить ноды в админке

## Сменили `XUI_HOST` в `.env`

После правки **перезапустите** бота — host подтянется в ★ Primary. Или `/admin` → **Ноды** → **Редактировать**.

## `message caption is too long` (Happ / QR)

- Длинная `happ://crypt…` не влезает в caption (лимит 1024)
- Бот выносит ссылку в отдельное сообщение
- `git pull` + `vpn-bot-ctl.sh` → **2**

## Happ: ссылка не валидна / plain URL вместо crypt

См. [Конфигурация → Happ](configuration.md#happ--шифрование-ссылки-подписки). Логи: `Happ crypto … failed`.

## Дубли нод

```bash
python scripts/dedupe_nodes.py
```

## Redis / FSM

`REDIS_URL задан, но Redis недоступен`:

```bash
redis-cli ping
sudo systemctl status redis-server
sudo bash deploy/vpn-bot-ctl.sh   # → 1
```

Откат: убрать `REDIS_URL` → FSM в RAM.

## `pip install` — externally-managed-environment

```bash
.venv/bin/pip install -r requirements.txt
```

Пункт **1** в `vpn-bot-ctl.sh` ставит в `.venv` автоматически.

## Обновление на сервере

```bash
sudo bash deploy/vpn-bot-ctl.sh update   # git pull + restart
# или меню → 2; при новых зависимостях → 1
```

---

**Назад:** [← Разработка](development.md) · **Оглавление:** [Документация](README.md)
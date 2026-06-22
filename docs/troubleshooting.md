[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md)

---

# Troubleshooting

## Бот не отвечает в Telegram

- Запущен ли бот? (`python run_all.py` или отдельно `python run_bot.py`)
- В логах: `Подключён @username` и `Polling started`
- Верный `BOT_TOKEN`?

## Webhook не приходит

- `curl -X POST PUBLIC_WEBHOOK_URL` — доступен ли URL?
- Callback URL в Platega совпадает с `PUBLIC_WEBHOOK_URL`
- nginx проксирует на `WEBHOOK_PORT`
- `TEST_MODE=false` для реальных платежей

## Оплата прошла, ключа нет

- Логи `app.py`: `Platega callback: tx=... status=CONFIRMED`
- Очередь не переполнена (`FULFILLMENT_QUEUE_MAX_SIZE`)
- Ноды online в админке
- `XUI_HOST` без лишнего `/panel/`

## Ошибка 3x-ui / таймаут

- Увеличьте `XUI_PANEL_CONCURRENCY` осторожно (нагрузка на панель)
- Проверьте `XUI_TOKEN` и secret path
- `LOG_LEVEL=DEBUG` для деталей API

## Сменили `XUI_HOST` в `.env`, а бот ходит на старый URL

Адрес ★ основной ноды хранится в `data/bot.db` (`xui_nodes`). После правки `.env` **перезапустите** бота — при старте host подтянется из `XUI_HOST` (в логах: `primary host обновлён из .env`). Без перезапуска или без обновления кода — `/admin` → **Ноды** → ★ Primary → **Редактировать** → новый host.

## `message caption is too long` при выдаче ключа / trial

- При `crypt3_local` / `crypt5_api` ссылка `happ://crypt…` ~700 символов — не влезает в caption фото (лимит Telegram **1024**).
- Бот выносит длинную ссылку в **отдельное сообщение** после QR (обновление после `69e3cb7`).
- Если ошибка остаётся — `git pull` и перезапуск бота.

## Happ: «ссылка не валидна» при вставке `happ://crypt…`

- RSA-ключ из [документации Happ](https://www.happ.su/main/dev-docs/crypto-link) даёт префикс **`happ://crypt3/`** — режим **`crypt3_local`**.
- Если crypt3 не принимается вашей версией Happ — **`crypt5_api`** (`happ://crypt5/…`).
- Копируйте ссылку **целиком** из отдельного сообщения (после QR), без переносов строк.

## Happ: вместо `happ://crypt…` отдаётся обычная ссылка

- В логах: `Happ crypto … failed` — смотрите причину (таймаут API, нет `cryptography`)
- Режим **Crypt5 API**: нужен доступ VPS → `crypto.happ.su`
- Режим **Crypt4 локально**: `pip install cryptography` (зависимость в `requirements.txt`)
- Слишком длинный `SUBSCRIPTION_BASE_URL` (>501 байт) — Crypt4 не сработает, будет fallback
- Сменили режим в `/admin` → **🔐 Happ** — кэш сбрасывается автоматически

## Дубли нод

```bash
python scripts/dedupe_nodes.py
```

---

**Назад:** [← Разработка](development.md) · **Оглавление:** [Документация](README.md)

*Вопросы по настройке — смотрите логи `data/logs/` и разделы выше.*
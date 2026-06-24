[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Конфигурация (.env)

Полный шаблон: [`.env.example`](../.env.example)

## Telegram

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен от @BotFather |
| `BOT_ADMINS` | Telegram ID админов через запятую |

## Platega

| Переменная | Описание |
|------------|----------|
| `PLATEGA_MERCHANT_ID` | UUID мерчанта |
| `PLATEGA_SECRET` | Секрет для подписи callback |
| `PLATEGA_*_METHOD` | ID способов оплаты (СБП, карта, крипто и т.д.) |
| `PUBLIC_WEBHOOK_URL` | `https://домен/platega-webhook` — тот же path, что `WEBHOOK_PATH` |

## 3x-ui

| Переменная | Описание |
|------------|----------|
| `XUI_HOST` | `https://панель/secret-path/` **без** `/panel/` |
| `XUI_TOKEN` | API Token из панели (предпочтительно) |

При первом запуске `XUI_HOST` попадает в БД как ★ основная нода. При **перезапуске** бот синхронизирует host и учётные данные основной ноды из `.env` (если вы сменили CDN/домен — достаточно поправить `.env` и перезапустить). Альтернатива: `/admin` → **Ноды** → ★ Primary → **Редактировать**.
| `SUBSCRIPTION_BASE_URL` | База ссылки подписки до `{sub_id}` |
| `DEFAULT_SUBSCRIPTION_INBOUNDS` | ID инбаундов через запятую |
| `XUI_CLIENT_GROUP` | Группа клиентов в 3x-ui |

## Happ — шифрование ссылки подписки

Клиентам выдаётся ссылка для импорта в [Happ](https://www.happ.su). По умолчанию — обычный HTTPS URL; можно включить шифрование, чтобы пользователь не видел и не пересылал адрес подписки.

| Переменная | Значения | Описание |
|------------|----------|----------|
| `HAPP_CRYPTO_MODE` | `none` (по умолчанию) | Без шифрования — `https://…/{sub_id}` |
| | `crypt3_local` | Локальный RSA — ключ из [документации Happ](https://www.happ.su/main/dev-docs/crypto-link) → `happ://crypt3/…` |
| | `crypt5_api` | Запрос на `crypto.happ.su` → `happ://crypt5/…` |
| `HAPP_CRYPTO_API_URL` | URL | Endpoint Crypt5 (по умолчанию `https://crypto.happ.su/api-v2.php`) |
| `HAPP_CRYPTO_TIMEOUT_SEC` | секунды | Таймаут запроса Crypt5 API |

Режим можно переключить в `/admin` → **🔐 Happ** (сохраняется в БД и перекрывает `.env`). Зашифрованные ссылки кэшируются в памяти процесса бота.

**Рекомендация:** локально без API — **`crypt3_local`** (ключ из docs, префикс `happ://crypt3/`). Если не примется в вашей версии Happ — **`crypt5_api`**. Старое значение `crypt4_local` в `.env` бот читает как `crypt3_local`.

Документация Happ: [crypto-link](https://www.happ.su/main/dev-docs/crypto-link)

## Лимит одновременных подключений (limitIp)

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `TRIAL_LIMIT_IP` | `3` | Пробная подписка — уникальных IP одновременно |
| `PAID_LIMIT_IP` | `5` | Платная подписка |

Значения можно менять в `/admin` → **📱 Лимит IP** (сохраняется в БД и перекрывает `.env`). При сохранении бот обновляет `limitIp` существующим клиентам только на **основной** ноде — вторичные синхронизирует сама панель 3x-ui. Клиент видит лимит при выдаче ключа и в разделе «Подписка». `0` — без ограничения.

## Режимы

| Переменная | Продакшен | Разработка |
|------------|-----------|------------|
| `TEST_MODE` | `false` | `true` (симулятор Platega) |
| `START_BOT_IN_WEBAPP` | `false` | `false` или `true` (один процесс) |
| `ALLOW_DEBUG_ADMIN` | `false` | `true` (сброс БД в админке) |
| `LOG_LEVEL` | `INFO` | `DEBUG` при отладке |
| `BACKUP_ENABLED` | `true` | `false` — без автобэкапа |
| `BACKUP_INTERVAL` | `24h` | Интервал: `30m`, `6h`, `7d` (мин. 30m, макс. 30d); в админке можно переопределить |
| `BACKUP_LOCAL_RETAIN` | `5` | Сколько zip хранить в `data/backups/` |

**Запуск** (не переменные `.env`, а команды):

| Команда | Описание |
|---------|----------|
| `python run_all.py` | Webhook + Telegram, два процесса, одна команда |
| `python app.py` + `python run_bot.py` | То же, но отдельно (systemd в проде) |
| `START_BOT_IN_WEBAPP=true` + `python app.py` | Всё в одном процессе |

---

**Назад:** [← Установка](installation.md) · **Далее:** [Деплой →](deployment.md)
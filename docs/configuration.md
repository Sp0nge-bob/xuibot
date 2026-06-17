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
| `SUBSCRIPTION_BASE_URL` | База ссылки подписки до `{sub_id}` |
| `DEFAULT_SUBSCRIPTION_INBOUNDS` | ID инбаундов через запятую |
| `XUI_CLIENT_GROUP` | Группа клиентов в 3x-ui |

## Режимы

| Переменная | Продакшен | Разработка |
|------------|-----------|------------|
| `TEST_MODE` | `false` | `true` (симулятор Platega) |
| `START_BOT_IN_WEBAPP` | `false` | `false` или `true` (один процесс) |
| `ALLOW_DEBUG_ADMIN` | `false` | `true` (сброс БД в админке) |
| `LOG_LEVEL` | `INFO` | `DEBUG` при отладке |
| `BACKUP_ENABLED` | `true` | `false` — без ежедневного бэкапа |
| `BACKUP_HOUR_UTC` | `3` | Час отправки бэкапа (UTC) |
| `BACKUP_LOCAL_RETAIN` | `5` | Сколько zip хранить в `data/backups/` |

**Запуск** (не переменные `.env`, а команды):

| Команда | Описание |
|---------|----------|
| `python run_all.py` | Webhook + Telegram, два процесса, одна команда |
| `python app.py` + `python run_bot.py` | То же, но отдельно (systemd в проде) |
| `START_BOT_IN_WEBAPP=true` + `python app.py` | Всё в одном процессе |

---

**Назад:** [← Установка](installation.md) · **Далее:** [Деплой →](deployment.md)
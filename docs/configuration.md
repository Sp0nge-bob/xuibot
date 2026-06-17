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
| `START_BOT_IN_WEBAPP` | `false` | `false` или `true` |
| `ALLOW_DEBUG_ADMIN` | `false` | `true` (сброс БД в админке) |
| `LOG_LEVEL` | `INFO` | `DEBUG` при отладке |

---

**Назад:** [← Установка](installation.md) · **Далее:** [Деплой →](deployment.md)
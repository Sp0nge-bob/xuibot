[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Platega и платежи

## Поток оплаты

1. Пользователь выбирает тариф и способ оплаты.
2. Бот создаёт транзакцию в Platega, показывает ссылку.
3. Platega шлёт POST на `PUBLIC_WEBHOOK_URL` со статусом `CONFIRMED`.
4. Webhook кладёт задачу в очередь → создаётся клиент в 3x-ui → пользователь получает ссылку.

## Способы оплаты

В `/admin` → «Способы оплаты» включайте нужные методы. ID методов задаются в `.env` (`PLATEGA_SBP_METHOD` и др.).

## Безопасность webhook

- Проверка заголовков `X-MerchantId` и `X-Secret`
- Rate limit (`WEBHOOK_RATE_LIMIT_PER_MIN`)
- Идемпотентность повторных callback (`WEBHOOK_IDEMPOTENCY_TTL_SEC`)

---

**Назад:** [← 3x-ui](xui.md) · **Далее:** [Админка →](admin.md)
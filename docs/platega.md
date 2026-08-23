[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Platega и платежи

## Callback URL (личный кабинет + nginx)

Бот слушает путь `WEBHOOK_PATH` (по умолчанию `/platega-webhook`) на порту **8080**.
Публичный адрес задаётся в `.env` как **`PUBLIC_WEBHOOK_URL`**, например:

```text
https://your-domain.com/platega-webhook
```

Мастер `install.sh` в конце установки **печатает этот URL**. Его нужно:

1. **Вписать в личном кабинете Platega** (Callback / Webhook URL) — без этого Platega не пришлёт статус оплаты боту.
2. **Добавить в nginx** на HTTPS-сайте и проксировать на бота (`proxy_pass http://127.0.0.1:8080`) — фрагмент в [deployment.md](deployment.md#nginx-фрагмент).

Управление службами после установки: **`vpnplategabot`**.

## Поток оплаты

1. Пользователь выбирает тариф и способ оплаты.
2. Бот создаёт транзакцию в Platega, показывает ссылку.
3. Platega шлёт POST на `PUBLIC_WEBHOOK_URL` со статусом `CONFIRMED`.
4. Webhook кладёт задачу в очередь → создаётся/продлевается клиент в 3x-ui → пользователь получает **текст успеха**, затем QR и ссылку (`bot/fulfillment_delivery.py`).

## Способы оплаты

В `/admin` → «Способы оплаты» включайте нужные методы. ID методов задаются в `.env` (`PLATEGA_SBP_METHOD` и др.).

## Безопасность webhook

- Проверка заголовков `X-MerchantId` и `X-Secret`
- Rate limit (`WEBHOOK_RATE_LIMIT_PER_MIN`)
- Идемпотентность повторных callback (`WEBHOOK_IDEMPOTENCY_TTL_SEC`)

## Lockdown и оплаты

При **draining** (ручная блокировка с активными PENDING) новые счета не создаются; незавершённые платежи дорабатываются. При полной блокировке или недоступной ★ Primary — см. [Архитектура → lockdown](architecture.md#блокировка-бота-lockdown).

---

**Назад:** [← 3x-ui](xui.md) · **Далее:** [Админка →](admin.md)
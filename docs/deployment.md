[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Деплой в продакшен

## Чеклист

- [ ] `TEST_MODE=false`
- [ ] `ALLOW_DEBUG_ADMIN=false`
- [ ] `START_BOT_IN_WEBAPP=false`
- [ ] Заполнены `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET`
- [ ] `PUBLIC_WEBHOOK_URL` — HTTPS, доступен извне
- [ ] В ЛК Platega Callback URL = `PUBLIC_WEBHOOK_URL`
- [ ] nginx проксирует порт `WEBHOOK_PORT` (по умолчанию 8080)
- [ ] `curl https://домен/health` → `{"status":"ok"}`
- [ ] Оба systemd-сервиса в статусе `active`
- [ ] `/admin` → настроены цены, способы оплаты, ноды
- [ ] Тестовый платёж → ключ в боте + клиент в 3x-ui

## nginx (фрагмент)

```nginx
location /platega-webhook {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
location /health {
    proxy_pass http://127.0.0.1:8080;
}
```

---

**Назад:** [← Конфигурация](configuration.md) · **Далее:** [3x-ui →](xui.md)
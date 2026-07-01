[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Деплой в продакшен

Перед выбором сервера: [Системные требования VPS](requirements.md).

## Чеклист

- [ ] `TEST_MODE=false` (или не переопределён в админке)
- [ ] `ALLOW_DEBUG_ADMIN=false`
- [ ] `START_BOT_IN_WEBAPP=false`
- [ ] `redis-server` → `PONG`; в `.env` задан `REDIS_URL` (пункт **1** в `vpn-bot-ctl.sh`)
- [ ] `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET`
- [ ] `PUBLIC_WEBHOOK_URL` — HTTPS, доступен извне
- [ ] Callback URL в ЛК Platega = `PUBLIC_WEBHOOK_URL`
- [ ] nginx проксирует `WEBHOOK_PORT` (8080)
- [ ] `curl https://домен/health` → `{"status":"ok"}`
- [ ] Оба systemd-сервиса `active`
- [ ] `/admin` → тарифы, оплата, ноды, inbounds
- [ ] Тестовый платёж → ключ + клиент в 3x-ui
- [ ] В логах: `FSM storage: Redis`

## Обновление

### Только код (типично после `git pull`)

```bash
cd /opt/vpn-bot   # или ваш APP_DIR
sudo bash deploy/vpn-bot-ctl.sh
# → 2   (git pull + restart)
```

Или:

```bash
sudo bash deploy/vpn-bot-ctl.sh update
```

### Полное обновление (venv, redis, unit-файлы)

```bash
git pull
sudo bash deploy/vpn-bot-ctl.sh
# → 1
```

Используйте после смены зависимостей в `pyproject.toml` или при «починке» окружения.

### Только перезапуск

```bash
sudo bash deploy/vpn-bot-ctl.sh
# → 3
```

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

## После деплоя

- `/admin` → **Обзор** → **Диагностика** — техсостояние (webhook, ноды, Redis)
- При проблемах — раздел «Рекомендации» в диагностике или [Troubleshooting](troubleshooting.md)

---

**Назад:** [← Конфигурация](configuration.md) · **Далее:** [3x-ui →](xui.md)
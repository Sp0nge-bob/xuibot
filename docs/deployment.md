[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Деплой в продакшен

Перед выбором сервера: [Системные требования VPS](requirements.md) (500 / 1000 / 3000+ подписок).

## Чеклист

- [ ] `TEST_MODE=false`
- [ ] `ALLOW_DEBUG_ADMIN=false`
- [ ] `START_BOT_IN_WEBAPP=false`
- [ ] `redis-server` запущен (`redis-cli ping` → `PONG`); в `.env` задан `REDIS_URL` (пункт **1** в `vpn-bot-ctl.sh` делает это автоматически)
- [ ] Заполнены `PLATEGA_MERCHANT_ID`, `PLATEGA_SECRET`
- [ ] `PUBLIC_WEBHOOK_URL` — HTTPS, доступен извне
- [ ] В ЛК Platega Callback URL = `PUBLIC_WEBHOOK_URL`
- [ ] nginx проксирует порт `WEBHOOK_PORT` (по умолчанию 8080)
- [ ] `curl https://домен/health` → `{"status":"ok"}`
- [ ] Оба systemd-сервиса в статусе `active`
- [ ] `/admin` → настроены цены, способы оплаты, ноды
- [ ] Тестовый платёж → ключ в боте + клиент в 3x-ui
- [ ] В логах Telegram: `FSM storage: Redis` (не `MemoryStorage`)

## Обновление после `git pull`

```bash
cd ~/vpn-platega-bot   # или /opt/vpn-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo bash deploy/vpn-bot-ctl.sh
# → 1   (обновить venv, redis, unit-файлы)
# или → 2   (только перезапуск, если зависимости уже стоят)
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

---

**Назад:** [← Конфигурация](configuration.md) · **Далее:** [3x-ui →](xui.md)
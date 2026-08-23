[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Деплой в продакшен

Перед выбором сервера: [Системные требования VPS](requirements.md).

**Python на VPS:** 3.11–3.14. `deploy/lib/python.sh` / пункт **1** ctl создаёт venv из самой новой доступной (`python3.14` … `python3.11`).

## Чеклист

- [ ] Python 3.11–3.14 в venv (`.venv/bin/python -V`)
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

### Обновление кода

| Цель | Меню | CLI |
|------|------|-----|
| **Stable** (рекомендуется) | **2** | `sudo bash deploy/vpn-bot-ctl.sh update` |
| **Edge** (свежий main) | **3** | `sudo bash deploy/vpn-bot-ctl.sh update --edge` |

Архив с GitHub; `.env` / `data/` / `.venv` не трогаются. Версия пишется в `.deploy_meta`.

Нет релизов → пункт **2** сообщит об этом; используйте пункт **3** или дождитесь Release.

Bootstrap / починка ctl:

```bash
curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
  | sudo bash -s -- /opt/vpn-bot
```

### Полное обновление окружения (venv, redis, unit-файлы)

```bash
sudo bash deploy/vpn-bot-ctl.sh
# → 1
```

### Только перезапуск

```bash
sudo bash deploy/vpn-bot-ctl.sh
# → 4
```

## nginx (фрагмент)

Тот же URL, что в `PUBLIC_WEBHOOK_URL` и в **личном кабинете Platega** (Callback / Webhook URL), должен отдаваться через nginx на процесс webhook (`127.0.0.1:8080`). После `install.sh` скрипт печатает этот адрес в блоке «Webhook (Platega)».

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

Управление: `vpnplategabot` (или `sudo bash deploy/vpn-bot-ctl.sh`).

## После деплоя

- `/admin` → **Обзор** → **Диагностика** — техсостояние (webhook, ноды, Redis)
- При проблемах — раздел «Рекомендации» в диагностике или [Troubleshooting](troubleshooting.md)

---

**Назад:** [← Конфигурация](configuration.md) · **Далее:** [3x-ui →](xui.md)
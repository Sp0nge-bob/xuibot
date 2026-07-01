[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Troubleshooting](troubleshooting.md)

---

# Разработка и отладка

## Тестовый режим

`TEST_MODE=true` в `.env` — симулятор Platega без реальных денег. Клиенты в 3x-ui создаются как в проде.

```env
TEST_MODE=true
ALLOW_DEBUG_ADMIN=true
LOG_LEVEL=DEBUG
```

Запуск:

- `python run_all.py` — webhook + Telegram
- `python run_bot.py` — только бот (симулятор не требует webhook)

**Runtime:** в `/admin` → **Отладка** можно включить/выключить TEST_MODE без перезапуска (сохраняется в БД). Сброс — «TEST_MODE из .env».

Перед продом: `TEST_MODE=false`, сброс override в отладке, реальные credentials Platega.

## Логи и мониторинг

| Уровень | Что видно |
|---------|-----------|
| `INFO` | Старт, платежи, деактивация, sync, lockdown |
| `DEBUG` | Тело webhook, health нод, debounce |

| Путь | Описание |
|------|----------|
| `data/logs/bot.log` | Текущая сессия (`tail -f`) |
| `data/logs/botlog_*.log` | Архивы после рестарта (макс. `LOG_ARCHIVE_RETAIN`) |

**Health:** `GET /health` на порту webhook (`WEBHOOK_PORT`).

**Админка:**

- `/admin` → **Обзор** → **Диагностика** — техсостояние (процессы, webhook, VPN, Redis)
- `/admin` → **VPN** → **Ноды** → «Проверить»

## Скрипты

| Путь | Назначение |
|------|------------|
| `scripts/list_inbounds.py` | ID инбаундов с панели |
| `scripts/dedupe_nodes.py` | Дубликаты нод в БД |
| `scripts/dev/test_pending_flow.py` | Симуляция PENDING (TEST_MODE) |
| `scripts/dev/test_admin_diagnostics.py` | Unit-тесты форматирования диагностики |
| `scripts/dev/*` | Остальное — только разработка |

## UI и тексты

Дизайн-система экранов: [`ui/theme.py`](../ui/theme.py) (`screen()`, разделитель, кнопки).

---

**Назад:** [← Подписки](subscriptions.md) · **Далее:** [Troubleshooting →](troubleshooting.md)
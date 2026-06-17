[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Troubleshooting](troubleshooting.md)

---

# Разработка и отладка

## Тестовый режим

`TEST_MODE=true` — симулятор Platega без реальных денег. Клиенты в 3x-ui создаются как в проде.

```env
TEST_MODE=true
ALLOW_DEBUG_ADMIN=true
LOG_LEVEL=DEBUG
```

Запуск:

- `python run_all.py` — webhook + Telegram (полный цикл)
- `python run_bot.py` — только бот (webhook не нужен для симулятора Platega в TEST_MODE)

Перед продом: `TEST_MODE=false`, реальные credentials Platega.

## Логи и мониторинг

| Уровень | Что видно |
|---------|-----------|
| `INFO` | Старт, платежи (tx + status), деактивация подписок, sync |
| `DEBUG` | Тело webhook, health нод, debounce callback |

Файлы: `data/logs/` (последние `LOG_SESSION_RETAIN` сессий).

Health endpoint: `GET /health` на порту webhook.

Проверка нод вручную: `/admin` → Ноды → «Проверить все ноды».

## Скрипты

| Путь | Назначение |
|------|------------|
| `scripts/list_inbounds.py` | ID инбаундов с панели |
| `scripts/dedupe_nodes.py` | Очистка дубликатов в БД |
| `scripts/dev/*` | Скрипты разработки — не для прода |

---

**Назад:** [← Подписки](subscriptions.md) · **Далее:** [Troubleshooting →](troubleshooting.md)
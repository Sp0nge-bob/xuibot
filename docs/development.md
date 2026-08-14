[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Troubleshooting](troubleshooting.md)

---

# Разработка и отладка

## Python

| | |
|--|--|
| Поддерживаемые версии | **3.11–3.14** (`>=3.11,<3.15` в `pyproject.toml`) |
| Рекомендуемый venv | `python3.11` … `python3.14 -m venv .venv` |
| Проверка на 3.14 | `python scripts/dev/smoke_python314.py` (offline: compileall, импорты, SQLite, QR, промо, FastAPI routes) |

Smoke не поднимает polling и не требует живую панель; живой `get_me` / Primary — отдельно.

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
| `scripts/dev/smoke_python314.py` | Offline smoke: Python 3.11–3.14 (compileall, импорты, БД, QR, routes) |
| `scripts/dev/test_pending_flow.py` | Симуляция PENDING (TEST_MODE) |
| `scripts/dev/test_admin_diagnostics.py` | Unit-тесты форматирования диагностики |
| `scripts/dev/*` | Остальное — только разработка |

## Выдача подписки (fulfillment delivery)

После оплаты / grant-промо клиенту уходит:

1. **Текст успеха** сразу (кнопки, если нет отдельной ссылки)
2. **QR** (короткий caption) — upload в Telegram может занять секунды
3. **Ссылка** `happ://crypt…` отдельным сообщением (если длинная)

Так пользователь не ждёт QR, пока панель уже отработала. Логи: `fulfillment text/QR/link sent … in X.XXs`.

При продлении на Primary `groups/bulkAdd` пропускается, если клиент уже в группе бота.

## UI и тексты

Дизайн-система экранов: [`ui/theme.py`](../ui/theme.py) (`screen()`, разделитель, кнопки).

Клиентские тексты промокодов **не упоминают** стек 3x-ui — только понятные формулировки («активация может занять несколько секунд»).

---

**Назад:** [← Подписки](subscriptions.md) · **Далее:** [Troubleshooting →](troubleshooting.md)
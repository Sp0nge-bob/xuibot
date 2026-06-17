[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# 3x-ui и подписка

1. Бот подключается **только к главной панели** (`XUI_HOST`).
2. Вторичные ноды добавляются в админке → «Ноды».
3. На нодах подписка **выключена** — одна ссылка с главной панели.
4. `DEFAULT_SUBSCRIPTION_INBOUNDS` — по одному inbound с каждой ноды в общей подписке.
5. `SUBSCRIPTION_BASE_URL` — маскировка nginx (например `/api/v4/GET/`).

Синхронизация клиентов на вторичные ноды — автоматически (очередь + полный sync раз в сутки).

## Утилиты

```bash
python scripts/list_inbounds.py    # список ID инбаундов
python scripts/dedupe_nodes.py     # убрать дубликаты нод в БД
```

| Путь | Назначение |
|------|------------|
| `scripts/list_inbounds.py` | ID инбаундов с панели |
| `scripts/dedupe_nodes.py` | Очистка дубликатов в БД |
| `scripts/dev/*` | Скрипты разработки — не использовать в проде |

---

**Назад:** [← Деплой](deployment.md) · **Далее:** [Platega →](platega.md)
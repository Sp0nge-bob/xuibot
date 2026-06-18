[← Документация](README.md) · [Архитектура](architecture.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# 3x-ui и подписка

1. Бот подключается **только к главной панели** (`XUI_HOST`).
2. Вторичные ноды добавляются в админке → «Ноды».
3. На нодах подписка **выключена** — одна ссылка с главной панели.
4. `DEFAULT_SUBSCRIPTION_INBOUNDS` — по одному inbound с каждой ноды в общей подписке.
5. `SUBSCRIPTION_BASE_URL` — маскировка nginx (например `/api/v4/GET/`).

## Ссылка для клиента (Happ)

После оплаты бот отправляет ссылку подписки и QR. Функция `build_sub_link()` собирает URL из `SUBSCRIPTION_BASE_URL` + `{sub_id}`.

Опционально — шифрование для приложения Happ (см. [конфигурацию](configuration.md#happ--шифрование-ссылки-подписки)):

| Режим | Результат |
|-------|-----------|
| `none` | `https://sub.example.com/api/v4/GET/abc123` |
| `crypt5_api` | `happ://crypt5/…` (через API Happ) |
| `crypt4_local` | `happ://crypt4/…` (RSA на VPS, без внешних запросов) |

Переключение: `/admin` → **🔐 Happ**. При ошибке шифрования бот отдаёт plain URL (fallback).

Синхронизация клиентов на вторичные ноды — автоматически (очередь + полный sync раз в сутки). Можно отключить в `/admin` → **Ноды** → «Выключить автосинк», если достаточно только главной панели.

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
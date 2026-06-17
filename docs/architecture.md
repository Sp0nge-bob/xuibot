[← Документация](README.md) · [Установка](installation.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Архитектура

В продакшене бот работает **двумя процессами**:

```mermaid
flowchart LR
    TG[Telegram] --> BOT[run_bot.py\npolling + scheduler]
    PL[Platega] --> APP[app.py\nFastAPI webhook]
    APP --> Q[Очередь fulfillment]
    Q --> XUI[3x-ui API]
    BOT --> XUI
    BOT --> DB[(SQLite)]
    APP --> DB
```

| Процесс | Файл | Задачи |
|---------|------|--------|
| Webhook | `python app.py` | Приём callback Platega, rate limit, идемпотентность, очередь выдачи ключей |
| Бот | `python run_bot.py` | Меню, оплата, админка, планировщик (истечение подписок, sync нод) |

**Способы запуска:**

| Команда | Когда использовать |
|---------|-------------------|
| `python run_all.py` | Локально и на VPS без systemd — одна команда, два процесса |
| `python app.py` + `python run_bot.py` | Продакшен с systemd (два unit-файла) |
| `START_BOT_IN_WEBAPP=true` → `python app.py` | Отладка в одном процессе, **не для прода** |

---

**Далее:** [Установка →](installation.md)
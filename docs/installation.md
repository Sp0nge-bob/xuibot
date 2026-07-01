[← Документация](README.md) · [Архитектура](architecture.md) · [Конфигурация](configuration.md) · [Деплой](deployment.md) · [3x-ui](xui.md) · [Platega](platega.md) · [Админка](admin.md) · [Подписки](subscriptions.md) · [Разработка](development.md) · [Troubleshooting](troubleshooting.md)

---

# Установка

**Требования:** Python 3.11–3.13, доступ к главной панели 3x-ui, HTTPS-домен для webhook.

```bash
cd /opt/vpn-bot
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

Заполните `.env` (см. [Конфигурация](configuration.md)), затем запустите бота.

**Одна команда** (webhook + Telegram):

```bash
python run_all.py
```

Или в двух терминалах:

```bash
python app.py       # webhook Platega
python run_bot.py   # Telegram polling
```

Для отладки в одном процессе: `START_BOT_IN_WEBAPP=true`, затем `python app.py`.

## systemd (`deploy/vpn-bot-ctl.sh`)

Интерактивное меню:

```bash
sudo bash deploy/vpn-bot-ctl.sh
```

| Пункт | Действие |
|-------|----------|
| **1** | Установить / обновить полностью: venv, pip, redis-server, `REDIS_URL`, права, unit-файлы, запуск |
| **2** | **Обновить бота:** `git pull --ff-only` + перезапуск служб (без переустановки venv) |
| **3** | Быстрый перезапуск служб |
| **4** | Статус служб + Redis |
| **5** | Логи `tail -f` |
| **6** | Остановить службы |
| **7** | Удалить unit-файлы |

**Первая установка:** пункт **1** после заполнения `.env`.

**Обычное обновление кода:** пункт **2** или:

```bash
sudo bash deploy/vpn-bot-ctl.sh update
```

**Если изменился `pyproject.toml` / новые зависимости:** пункт **1**.

**Redis:** пункт 1 на Debian/Ubuntu ставит `redis-server` и добавляет `REDIS_URL=redis://127.0.0.1:6379/0`, если строки нет в `.env`.

Алиас: `sudo bash deploy/install-systemd.sh` (то же меню).

Неинтерактивно:

```bash
sudo bash deploy/vpn-bot-ctl.sh install   # полная установка
sudo bash deploy/vpn-bot-ctl.sh update    # git pull + restart
sudo bash deploy/vpn-bot-ctl.sh restart # только restart
```

Unit-шаблоны: [`deploy/systemd/*.template`](../deploy/systemd/).

---

**Назад:** [← Архитектура](architecture.md) · **Далее:** [Конфигурация →](configuration.md)
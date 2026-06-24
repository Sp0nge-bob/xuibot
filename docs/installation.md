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

**Одна команда** (webhook + Telegram, два процесса):

```bash
python run_all.py
```

Или в двух терминалах:

```bash
python app.py       # терминал 1 — webhook Platega
python run_bot.py   # терминал 2 — Telegram polling
```

Для отладки в одном процессе: `START_BOT_IN_WEBAPP=true` в `.env`, затем `python app.py`.

## systemd (пример)

Меню systemd — **пункт 1 делает всё сам** (venv, pip, права, unit-файлы, запуск). Подходит и для первой установки, и после `git pull`:

```bash
git pull
sudo bash deploy/vpn-bot-ctl.sh
# → 1
```

Алиас: `sudo bash deploy/install-systemd.sh` (то же самое).

Перед первым запуском заполните `.env` (или скрипт создаст его из `.env.example`).

Неинтерактивно: `sudo bash deploy/vpn-bot-ctl.sh install`

Unit-шаблоны: [`deploy/systemd/*.template`](../deploy/systemd/) — подставляются скриптом автоматически.

---

**Назад:** [← Архитектура](architecture.md) · **Далее:** [Конфигурация →](configuration.md)
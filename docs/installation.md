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

Интерактивное меню (создаёт пользователя `vpnbot`, unit-файлы, автозапуск):

```bash
sudo bash deploy/install-systemd.sh
```

Пункты меню: установить · проверить статус · остановить · удалить · выход.

Неинтерактивно:

```bash
sudo bash deploy/install-systemd.sh install -d /opt/vpn-bot -u vpnbot
sudo bash deploy/install-systemd.sh status
sudo bash deploy/install-systemd.sh stop
sudo bash deploy/install-systemd.sh uninstall
```

Ручная установка — шаблоны в [`deploy/systemd/`](../deploy/systemd/):

- `vpn-bot-web.service` — webhook Platega
- `vpn-bot-telegram.service` — Telegram polling

```bash
sudo cp deploy/systemd/vpn-bot-web.service /etc/systemd/system/
sudo cp deploy/systemd/vpn-bot-telegram.service /etc/systemd/system/
# При необходимости отредактируйте User и WorkingDirectory
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-bot-web vpn-bot-telegram
```

---

**Назад:** [← Архитектура](architecture.md) · **Далее:** [Конфигурация →](configuration.md)
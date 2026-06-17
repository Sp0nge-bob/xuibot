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

Заполните `.env` (см. [Конфигурация](configuration.md)), затем:

```bash
python app.py       # терминал 1
python run_bot.py   # терминал 2
```

## systemd (пример)

Готовые unit-файлы в репозитории:

- [`deploy/systemd/vpn-bot-web.service`](../deploy/systemd/vpn-bot-web.service) — webhook Platega
- [`deploy/systemd/vpn-bot-telegram.service`](../deploy/systemd/vpn-bot-telegram.service) — Telegram polling

```bash
sudo cp deploy/systemd/vpn-bot-web.service /etc/systemd/system/
sudo cp deploy/systemd/vpn-bot-telegram.service /etc/systemd/system/
# При необходимости отредактируйте User и WorkingDirectory
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-bot-web vpn-bot-telegram
```

---

**Назад:** [← Архитектура](architecture.md) · **Далее:** [Конфигурация →](configuration.md)
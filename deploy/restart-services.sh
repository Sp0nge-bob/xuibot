#!/usr/bin/env bash
# Перезапуск vpn-bot-telegram + vpn-bot-web (systemd).
# Вызывается из deploy/vpn-bot-ctl.sh и командой /reboot в Telegram (через sudo).
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
TELEGRAM_UNIT="vpn-bot-telegram.service"
WEB_UNIT="vpn-bot-web.service"

rm -f "$APP_DIR/data/.polling.lock"
systemctl restart "$TELEGRAM_UNIT"
systemctl restart "$WEB_UNIT"
# shellcheck shell=bash
# Системная команда vpnplategabot → deploy/vpn-bot-ctl.sh (аналог x-ui)

VPNPLATEGABOT_BIN="${VPNPLATEGABOT_BIN:-/usr/local/bin/vpnplategabot}"

install_vpnplategabot_command() {
    : "${APP_DIR:?}"
    local ctl="$APP_DIR/deploy/vpn-bot-ctl.sh"
    if [[ ! -f "$ctl" ]]; then
        warn "Нет $ctl — команда vpnplategabot не установлена"
        return 1
    fi
    [[ -x "$ctl" ]] || chmod 755 "$ctl"

    mkdir -p "$(dirname "$VPNPLATEGABOT_BIN")"
    cat >"$VPNPLATEGABOT_BIN" <<EOF
#!/usr/bin/env bash
# VPN Shop Bot — ярлык на ctl (создаётся install / пункт 1)
# Не редактируйте вручную: перезаписывается при установке.
set -euo pipefail
APP_DIR=$(printf '%q' "$APP_DIR")
CTL="\$APP_DIR/deploy/vpn-bot-ctl.sh"
if [[ ! -f "\$CTL" ]]; then
    echo "ERR: не найден \$CTL — бот удалён или путь сменился" >&2
    echo "Установка: curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh | sudo bash" >&2
    exit 1
fi
if [[ "\${EUID:-\$(id -u)}" -ne 0 ]]; then
    exec sudo -- "\$CTL" "\$@"
fi
exec bash "\$CTL" "\$@"
EOF
    chmod 755 "$VPNPLATEGABOT_BIN"
    ok "Команда: $VPNPLATEGABOT_BIN  →  vpnplategabot"
    return 0
}


remove_vpnplategabot_command() {
    if [[ -f "$VPNPLATEGABOT_BIN" ]]; then
        rm -f "$VPNPLATEGABOT_BIN"
        ok "Удалена команда $VPNPLATEGABOT_BIN"
    else
        log "Команда vpnplategabot уже нет"
    fi
}


# Если ярлыка нет (обновились со старого ctl) — поставить при входе в меню
ensure_vpnplategabot_command() {
    : "${APP_DIR:?}"
    if [[ -x "$VPNPLATEGABOT_BIN" ]]; then
        # уже есть — обновить путь APP_DIR на случай переноса
        if ! grep -qF "$APP_DIR" "$VPNPLATEGABOT_BIN" 2>/dev/null; then
            install_vpnplategabot_command || true
        fi
        return 0
    fi
    install_vpnplategabot_command || true
}

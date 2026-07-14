# shellcheck shell=bash
# sudoers для /reboot: SERVICE_USER может перезапускать службы без пароля

install_restart_sudoers() {
    local script="$APP_DIR/deploy/restart-services.sh"
    local dest="/etc/sudoers.d/vpn-bot-restart"

    if [[ ! -f "$script" ]]; then
        warn "Нет $script — sudoers для /reboot не установлен"
        return 0
    fi

    chmod 755 "$script"
    cat >"$dest" <<EOF
# VPN Bot: команда /reboot в Telegram ($SERVICE_USER)
$SERVICE_USER ALL=(root) NOPASSWD: $script
EOF
    chmod 440 "$dest"

    if command -v visudo >/dev/null 2>&1; then
        if ! visudo -cf "$dest" >/dev/null 2>&1; then
            rm -f "$dest"
            warn "sudoers невалиден — /reboot через sudo недоступен"
            return 1
        fi
    fi

    ok "sudoers для /reboot: $dest"
    return 0
}
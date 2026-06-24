# shellcheck shell=bash
# systemd unit-файлы, запуск, статус

TEMPLATE_DIR="$DEPLOY_DIR/systemd"

render_template() {
    local template="$1"
    local dst="$2"
    sed \
        -e "s|@APP_DIR@|$APP_DIR|g" \
        -e "s|@SERVICE_USER@|$SERVICE_USER|g" \
        -e "s|@VENV_BIN@|$VENV_BIN|g" \
        "$template" >"$dst"
    chmod 644 "$dst"
}

write_units() {
    log "Unit-файлы → $SYSTEMD_DIR"
    render_template "$TEMPLATE_DIR/vpn-bot-telegram.service.template" \
        "$SYSTEMD_DIR/$TELEGRAM_UNIT"
    render_template "$TEMPLATE_DIR/vpn-bot-web.service.template" \
        "$SYSTEMD_DIR/$WEB_UNIT"
}

stop_stray_processes() {
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    pkill -f "$APP_DIR/run_bot.py" 2>/dev/null || true
    pkill -f "$APP_DIR/app.py" 2>/dev/null || true
    rm -f "$APP_DIR/data/.polling.lock"
}

show_service_logs() {
    local unit="$1"
    local lines="${2:-25}"
    warn "Журнал $unit:"
    journalctl -u "$unit" -n "$lines" --no-pager 2>/dev/null || true
}

wait_for_service() {
    local unit="$1"
    local attempts="${2:-8}"
    local i
    for ((i = 1; i <= attempts; i++)); do
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            return 0
        fi
        sleep 2
    done
    return 1
}

verify_services() {
    local failed=0
    if ! wait_for_service "$TELEGRAM_UNIT"; then
        warn "$TELEGRAM_UNIT не active"
        show_service_logs "$TELEGRAM_UNIT" 30
        failed=1
    else
        ok "$TELEGRAM_UNIT active"
    fi
    if ! wait_for_service "$WEB_UNIT"; then
        warn "$WEB_UNIT не active"
        show_service_logs "$WEB_UNIT" 30
        failed=1
    else
        ok "$WEB_UNIT active"
    fi
    return "$failed"
}

start_services() {
    stop_stray_processes
    write_units
    systemctl daemon-reload
    systemctl enable "$TELEGRAM_UNIT" "$WEB_UNIT"
    log "Запуск сервисов"
    systemctl restart "$TELEGRAM_UNIT"
    systemctl restart "$WEB_UNIT"
    verify_services
}

stop_services() {
    log "Останавливаем сервисы"
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    ok "Службы остановлены"
}

uninstall_services() {
    log "Удаляем unit-файлы"
    systemctl disable --now "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$TELEGRAM_UNIT" "$SYSTEMD_DIR/$WEB_UNIT"
    systemctl daemon-reload
    rm -f "$STATE_FILE"
    ok "Службы удалены"
}

unit_state_label() {
    local unit="$1"
    if ! systemctl cat "$unit" &>/dev/null; then
        warn "не установлен"
        return
    fi
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        ok "active"
    else
        warn "inactive / ошибка"
    fi
}

show_status() {
    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  vpn-bot-telegram\n'
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    unit_state_label "$TELEGRAM_UNIT"
    systemctl --no-pager status "$TELEGRAM_UNIT" 2>/dev/null | head -n 12 || true
    if systemctl cat "$TELEGRAM_UNIT" &>/dev/null && ! systemctl is-active --quiet "$TELEGRAM_UNIT" 2>/dev/null; then
        show_service_logs "$TELEGRAM_UNIT" 15
    fi

    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  vpn-bot-web\n'
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    unit_state_label "$WEB_UNIT"
    systemctl --no-pager status "$WEB_UNIT" 2>/dev/null | head -n 12 || true
    if systemctl cat "$WEB_UNIT" &>/dev/null && ! systemctl is-active --quiet "$WEB_UNIT" 2>/dev/null; then
        show_service_logs "$WEB_UNIT" 15
    fi
    echo
    if [[ -f "$STATE_FILE" ]]; then
        log "Каталог: $APP_DIR | пользователь: $SERVICE_USER"
    fi
}
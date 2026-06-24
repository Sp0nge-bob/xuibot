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

restart_services() {
    load_config
    if ! unit_is_installed "$TELEGRAM_UNIT" || ! unit_is_installed "$WEB_UNIT"; then
        warn "Службы не установлены — сначала пункт 1 (установить / обновить)"
        return 1
    fi
    log "Быстрый перезапуск (без обновления venv и unit-файлов)"
    rm -f "$APP_DIR/data/.polling.lock"
    systemctl restart "$TELEGRAM_UNIT"
    systemctl restart "$WEB_UNIT"
    if verify_services; then
        ok "Службы перезапущены"
        return 0
    fi
    warn "После перезапуска не все службы active — см. journalctl выше"
    return 1
}

unit_is_installed() {
    local unit="$1"
    [[ -f "$SYSTEMD_DIR/$unit" ]]
}

uninstall_services() {
    log "Останавливаем и удаляем службы"
    systemctl disable --now "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$TELEGRAM_UNIT" "$SYSTEMD_DIR/$WEB_UNIT"
    systemctl daemon-reload
    systemctl reset-failed "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$STATE_FILE"
    ok "Службы удалены (unit-файлов нет)"
}

unit_state_label() {
    local unit="$1"
    if ! unit_is_installed "$unit"; then
        ok "не установлен"
        return
    fi
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        ok "active"
    else
        warn "inactive / ошибка"
    fi
}

show_unit_block() {
    local unit="$1"
    local title="$2"

    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "$title"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if ! unit_is_installed "$unit"; then
        ok "не установлен — $SYSTEMD_DIR/$unit отсутствует"
        return
    fi

    unit_state_label "$unit"
    systemctl --no-pager status "$unit" 2>/dev/null | head -n 12 || true
    if ! systemctl is-active --quiet "$unit" 2>/dev/null; then
        show_service_logs "$unit" 15
    fi
}

show_status() {
    show_unit_block "$TELEGRAM_UNIT" "vpn-bot-telegram"
    show_unit_block "$WEB_UNIT" "vpn-bot-web"
    echo
    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE" 2>/dev/null || true
        log "Каталог: ${APP_DIR:-?} | пользователь: ${SERVICE_USER:-vpnbot}"
    fi
}
# shellcheck shell=bash
# Просмотр логов бота в реальном времени

follow_all_logs() {
    load_config

    local log_dir="$APP_DIR/data/logs"
    local log_file="$log_dir/bot.log"
    local has_units=0

    if unit_is_installed "$TELEGRAM_UNIT" || unit_is_installed "$WEB_UNIT"; then
        has_units=1
    fi

    echo
    log "Логи в реальном времени — Ctrl+C чтобы вернуться в меню"
    echo
    printf '  Файл:   %s\n' "$log_file"
    if [[ "$has_units" -eq 1 ]]; then
        printf '  systemd: journalctl -fu %s -u %s\n' "$TELEGRAM_UNIT" "$WEB_UNIT"
    fi
    echo

    if [[ -f "$log_file" ]]; then
        tail -n 40 -F "$log_file"
        return 0
    fi

    if [[ "$has_units" -eq 1 ]]; then
        warn "Файл $log_file пока нет — показываем journalctl"
        journalctl -f -u "$TELEGRAM_UNIT" -u "$WEB_UNIT" --no-pager
        return 0
    fi

    warn "Лог не найден: $log_file"
    if [[ -d "$log_dir" ]]; then
        local latest
        latest="$(ls -1t "$log_dir"/botlog_*.log 2>/dev/null | head -n 1 || true)"
        if [[ -n "$latest" && -f "$latest" ]]; then
            log "Последний архив: $latest"
            tail -n 40 -F "$latest"
            return 0
        fi
    fi

    warn "Запустите бота (п. 1 — установить службы) или вручную: python run_bot.py"
    return 1
}
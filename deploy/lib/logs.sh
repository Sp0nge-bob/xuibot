# shellcheck shell=bash
# Просмотр логов: цветной follow + выход по q (обратно в меню)

# Подсветка типичных строк loguru / journald (без ломания UTF-8)
_colorize_log_stream() {
    local line plain
    # Unbuffered-ish line loop
    while IFS= read -r line || [[ -n "$line" ]]; do
        plain="$line"
        case "$plain" in
            *'| ERROR'*|*'| CRITICAL'*|*ERROR*|*CRITICAL*|*Traceback*)
                printf '%s%s%s\n' "${C_RED:-}" "$line" "${C_RESET:-}"
                ;;
            *'| WARNING'*|*'| WARN'*|*WARNING*)
                printf '%s%s%s\n' "${C_YELLOW:-}" "$line" "${C_RESET:-}"
                ;;
            *'| SUCCESS'*|*SUCCESS*)
                printf '%s%s%s\n' "${C_GREEN:-}" "$line" "${C_RESET:-}"
                ;;
            *'| DEBUG'*|*DEBUG*)
                printf '%s%s%s\n' "${C_DIM:-}" "$line" "${C_RESET:-}"
                ;;
            *'| INFO'*|*INFO*)
                # лёгкий акцент на INFO, без перекраса всей строки ярко
                if [[ "$plain" =~ ^[0-9]{4}- ]]; then
                    printf '%s%s%s\n' "${C_DIM:-}" "$line" "${C_RESET:-}"
                else
                    printf '%s\n' "$line"
                fi
                ;;
            *)
                printf '%s\n' "$line"
                ;;
        esac
    done
}

_logs_resolve_source() {
    # Sets: LOGS_KIND=file|journal|none  LOGS_PATH=...
    local log_dir="$APP_DIR/data/logs"
    local log_file="$log_dir/bot.log"

    LOGS_KIND="none"
    LOGS_PATH=""
    LOGS_LABEL=""

    if [[ -f "$log_file" ]]; then
        LOGS_KIND="file"
        LOGS_PATH="$log_file"
        LOGS_LABEL="bot.log"
        return 0
    fi

    if unit_is_installed "$TELEGRAM_UNIT" || unit_is_installed "$WEB_UNIT"; then
        LOGS_KIND="journal"
        LOGS_PATH="journal"
        LOGS_LABEL="journalctl (${TELEGRAM_UNIT} + ${WEB_UNIT})"
        return 0
    fi

    if [[ -d "$log_dir" ]]; then
        local latest
        latest="$(ls -1t "$log_dir"/botlog_*.log 2>/dev/null | head -n 1 || true)"
        if [[ -n "$latest" && -f "$latest" ]]; then
            LOGS_KIND="file"
            LOGS_PATH="$latest"
            LOGS_LABEL="$(basename "$latest") (архив)"
            return 0
        fi
    fi
    return 1
}

_logs_follow_with_q() {
    # Follow LOGS_KIND/LOGS_PATH until user presses q/Q (or Ctrl+C → меню)
    local feeder_pid=""
    local tty_restored=0
    local stop_requested=0

    _logs_restore_tty() {
        if [[ "$tty_restored" -eq 1 ]]; then
            return
        fi
        tty_restored=1
        if [[ -r /dev/tty ]]; then
            stty sane </dev/tty 2>/dev/null \
                || { stty echo icanon </dev/tty 2>/dev/null || true; }
        fi
    }

    _logs_stop_feeder() {
        local child
        if [[ -n "$feeder_pid" ]]; then
            # убить весь pipeline (tail + colorize)
            while read -r child; do
                kill "$child" 2>/dev/null || true
            done < <(pgrep -P "$feeder_pid" 2>/dev/null || true)
            kill "$feeder_pid" 2>/dev/null || true
            wait "$feeder_pid" 2>/dev/null || true
            feeder_pid=""
        fi
    }

    _logs_cleanup() {
        _logs_stop_feeder
        _logs_restore_tty
    }

    _logs_on_intr() {
        stop_requested=1
        _logs_cleanup
    }

    trap '_logs_on_intr' INT TERM
    trap '_logs_cleanup' EXIT

    # Snapshot (last lines), then live
    local sep='----'
    [[ "${UI_UTF8:-0}" -eq 1 ]] && sep='────'
    printf '\n  %s%s последние строки %s%s\n\n' "${C_DIM:-}" "$sep" "$sep" "${C_RESET:-}"
    case "$LOGS_KIND" in
        file)
            tail -n 50 "$LOGS_PATH" 2>/dev/null | _colorize_log_stream
            printf '\n  %s%s live %s%s  %sq%s — назад в меню\n\n' \
                "${C_DIM:-}" "$sep" "$sep" "${C_RESET:-}" \
                "${C_BOLD:-}${C_CYAN:-}" "${C_RESET:-}"
            tail -n 0 -F "$LOGS_PATH" 2>/dev/null | _colorize_log_stream &
            feeder_pid=$!
            ;;
        journal)
            journalctl -n 50 -u "$TELEGRAM_UNIT" -u "$WEB_UNIT" --no-pager 2>/dev/null \
                | _colorize_log_stream
            printf '\n  %s%s live %s%s  %sq%s — назад в меню\n\n' \
                "${C_DIM:-}" "$sep" "$sep" "${C_RESET:-}" \
                "${C_BOLD:-}${C_CYAN:-}" "${C_RESET:-}"
            journalctl -f -u "$TELEGRAM_UNIT" -u "$WEB_UNIT" --no-pager 2>/dev/null \
                | _colorize_log_stream &
            feeder_pid=$!
            ;;
        *)
            _logs_cleanup
            trap - EXIT INT TERM
            return 1
            ;;
    esac

    # Non-canonical input from tty so q works while tail writes to stdout
    if [[ -r /dev/tty ]]; then
        stty -echo -icanon time 1 min 0 </dev/tty 2>/dev/null || true
    fi

    local key=""
    while [[ "$stop_requested" -eq 0 ]]; do
        if [[ -n "$feeder_pid" ]] && ! kill -0 "$feeder_pid" 2>/dev/null; then
            warn "Поток логов завершился"
            break
        fi
        key=""
        if [[ -r /dev/tty ]]; then
            # shellcheck disable=SC2162
            read -r -n 1 -s -t 0.4 key </dev/tty || true
        else
            sleep 0.4
        fi
        case "$key" in
            q|Q)
                break
                ;;
        esac
    done

    _logs_cleanup
    trap - EXIT INT TERM
    printf '\n'
    ok "Выход из просмотра логов"
    return 0
}

follow_all_logs() {
    load_config

    if ! _logs_resolve_source; then
        warn "Лог не найден: $APP_DIR/data/logs/bot.log"
        warn "Запустите бота (п. 1 — установить службы) или: python run_bot.py"
        return 1
    fi

    if type ui_banner &>/dev/null; then
        ui_banner "logs" "${LOGS_LABEL}"
    else
        log "Логи: $LOGS_LABEL"
    fi

    printf '\n'
    ui_kv "Источник" "${LOGS_PATH}"
    printf '  %sУправление%s  %sq%s — назад в меню   %sCtrl+C%s — прервать\n' \
        "${C_DIM:-}" "${C_RESET:-}" \
        "${C_CYAN:-}${C_BOLD:-}" "${C_RESET:-}" \
        "${C_CYAN:-}${C_BOLD:-}" "${C_RESET:-}"

    _logs_follow_with_q
}

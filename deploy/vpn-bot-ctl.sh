#!/usr/bin/env bash
# VPN Bot — управление systemd (интерактивное меню).
#
#   sudo bash deploy/vpn-bot-ctl.sh

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"

# shellcheck source=lib/common.sh
source "$DEPLOY_DIR/lib/common.sh"
# shellcheck source=lib/python.sh
source "$DEPLOY_DIR/lib/python.sh"
# shellcheck source=lib/permissions.sh
source "$DEPLOY_DIR/lib/permissions.sh"
# shellcheck source=lib/systemd.sh
source "$DEPLOY_DIR/lib/systemd.sh"
# shellcheck source=lib/sudoers.sh
source "$DEPLOY_DIR/lib/sudoers.sh"
# shellcheck source=lib/reconcile.sh
source "$DEPLOY_DIR/lib/reconcile.sh"
# shellcheck source=lib/logs.sh
source "$DEPLOY_DIR/lib/logs.sh"
# shellcheck source=lib/redis.sh
source "$DEPLOY_DIR/lib/redis.sh"

pause_menu() {
    echo
    printf '%s' "${C_DIM}Enter — вернуться в меню…${C_RESET} "
    read -r _ </dev/tty
}

draw_menu() {
    local ver="неизвестно" app="?"
    if load_config 2>/dev/null; then
        ver="$(format_installed_version 2>/dev/null || echo неизвестно)"
        app="$APP_DIR"
    fi

    clear 2>/dev/null || printf '\n'
    ui_banner "VPN Bot  ·  systemd" "управление сервером"

    printf '\n'
    ui_kv "Каталог" "${C_CYAN}${app}${C_RESET}"
    ui_kv "Версия"  "${C_GREEN}${ver}${C_RESET}"
    ui_kv "User"    "${SERVICE_USER:-vpnbot}"
    printf '\n'
    ui_rule 46

    printf '\n  %sУстановка%s\n' "$C_DIM" "$C_RESET"
    ui_menu_item "1" "Установить / починить" "venv · Redis · unit'ы"

    printf '\n  %sОбновление кода%s\n' "$C_DIM" "$C_RESET"
    ui_menu_item "2" "Релиз (stable)"         "последний GitHub Release ★"
    ui_menu_item "3" "Коммит (edge)"          "последний main"

    printf '\n  %sСлужбы%s\n' "$C_DIM" "$C_RESET"
    ui_menu_item "4" "Перезапустить"          "быстрый restart"
    ui_menu_item "5" "Статус"                 "telegram · web · Redis"
    ui_menu_item "6" "Логи"                   "tail -f live"

    printf '\n  %sОпасная зона%s\n' "$C_DIM" "$C_RESET"
    ui_menu_item "7" "Остановить"             "stop units"
    ui_menu_item "8" "Удалить службы"         "uninstall units"

    printf '\n'
    ui_menu_item "0" "Выход"
    printf '\n'
    ui_rule 46
    printf '\n'
}

run_action() {
    echo
    if ( "$@" ); then
        echo
        ok "Готово"
        return 0
    fi
    echo
    err "Действие завершилось с ошибкой"
    return 1
}

interactive_menu() {
    require_root
    local choice

    while true; do
        draw_menu
        printf '%sВыберите пункт%s [%s0–8%s]: ' "$C_BOLD" "$C_RESET" "$C_CYAN" "$C_RESET"
        read -r choice </dev/tty

        case "$choice" in
            1)
                ui_header "Установка / починка окружения"
                run_action cmd_reconcile
                pause_menu
                ;;
            2)
                ui_header "Stable — последний GitHub Release"
                run_action cmd_update_bot_release
                pause_menu
                ;;
            3)
                ui_header "Edge — последний коммит main"
                run_action cmd_update_bot_edge
                pause_menu
                ;;
            4)
                ui_header "Перезапуск служб"
                run_action restart_services
                pause_menu
                ;;
            5)
                ui_header "Статус"
                load_config 2>/dev/null || true
                show_status
                if [[ -n "${APP_DIR:-}" ]]; then
                    echo
                    ui_kv "Версия" "$(format_installed_version)"
                fi
                pause_menu
                ;;
            6)
                ui_header "Логи (Ctrl+C — назад не сработает, остановите tail)"
                run_action follow_all_logs
                pause_menu
                ;;
            7)
                ui_header "Остановка служб"
                run_action stop_services
                pause_menu
                ;;
            8)
                printf '\n%s⚠  Удалить systemd unit-файлы?%s [' "$C_YELLOW" "$C_RESET"
                printf '%sy/N%s]: ' "$C_BOLD" "$C_RESET"
                read -r confirm </dev/tty
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    run_action uninstall_services
                else
                    log "Отменено"
                fi
                pause_menu
                ;;
            0|q|Q)
                printf '\n%sПока.%s\n\n' "$C_DIM" "$C_RESET"
                exit 0
                ;;
            *)
                err "Введите число от 0 до 8"
                sleep 1
                ;;
        esac
    done
}

print_help() {
    cat <<EOF
${C_BOLD}${C_CYAN}VPN Bot${C_RESET} — systemd CLI

  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh${C_RESET}                 интерактивное меню
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh install${C_RESET}         окружение (+ Redis)
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh update${C_RESET}          последний ${C_BOLD}Release${C_RESET} (stable)
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh update --edge${C_RESET}   последний коммит main
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh restart${C_RESET}
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh status${C_RESET}
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh logs${C_RESET}
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh stop${C_RESET}
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh uninstall${C_RESET}

Обновление ${C_DIM}не требует${C_RESET} локальный .git — архив с GitHub.
Сохраняются: ${C_BOLD}.env${C_RESET}, ${C_BOLD}data/${C_RESET}, ${C_BOLD}.venv/${C_RESET}.

С нуля / починить ctl:
  ${C_DIM}curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \\
    | sudo bash -s -- /opt/vpn-bot${C_RESET}
EOF
}

main() {
    local cmd="${1:-}"
    shift || true
    case "$cmd" in
        ""|menu)
            interactive_menu
            ;;
        install|reconcile)
            require_root
            ui_banner "VPN Bot" "install / reconcile"
            cmd_reconcile
            ;;
        update)
            local mode="release"
            while [[ $# -gt 0 ]]; do
                case "$1" in
                    --release|--stable|-r) mode="release" ;;
                    --edge|--commit|--main|-e) mode="edge" ;;
                    -h|--help)
                        cat <<'EOF'
update — обновить код и перезапустить службы

  sudo bash deploy/vpn-bot-ctl.sh update           # последний Release (stable)
  sudo bash deploy/vpn-bot-ctl.sh update --release
  sudo bash deploy/vpn-bot-ctl.sh update --edge    # последний коммит main
EOF
                        return 0
                        ;;
                    *) die "Неизвестный флаг update: $1 (см. update --help)" ;;
                esac
                shift
            done
            require_root
            if [[ "$mode" == "edge" ]]; then
                ui_banner "VPN Bot" "update · edge"
                cmd_update_bot_edge
            else
                ui_banner "VPN Bot" "update · stable"
                cmd_update_bot_release
            fi
            ;;
        update-release)
            require_root
            ui_banner "VPN Bot" "update · stable"
            cmd_update_bot_release
            ;;
        update-edge|pull)
            require_root
            ui_banner "VPN Bot" "update · edge"
            cmd_update_bot_edge
            ;;
        restart)
            require_root
            ui_banner "VPN Bot" "restart"
            restart_services
            ;;
        status)
            load_config 2>/dev/null || true
            ui_banner "VPN Bot" "status"
            show_status
            if [[ -n "${APP_DIR:-}" ]]; then
                echo
                ui_kv "Версия" "$(format_installed_version)"
            fi
            ;;
        logs|tail)
            require_root
            follow_all_logs
            ;;
        stop)
            require_root
            ui_banner "VPN Bot" "stop"
            stop_services
            ;;
        uninstall)
            require_root
            ui_banner "VPN Bot" "uninstall"
            uninstall_services
            ;;
        -h|--help)
            print_help
            ;;
        *)
            die "Неизвестная команда: $cmd (см. --help)"
            ;;
    esac
}

main "$@"

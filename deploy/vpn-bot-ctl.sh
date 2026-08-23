#!/usr/bin/env bash
# VPN Bot — управление systemd (интерактивное меню, стиль Charm/gum).
#
#   sudo bash deploy/vpn-bot-ctl.sh
#   NO_COLOR=1 — без ANSI

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
    printf '  %sEnter — вернуться в меню…%s ' "$C_DIM" "$C_RESET"
    read -r _ </dev/tty
}

draw_menu() {
    local ver="неизвестно" app="?" user="${SERVICE_USER:-vpnbot}"
    if load_config 2>/dev/null; then
        ver="$(format_installed_version 2>/dev/null || echo неизвестно)"
        app="$APP_DIR"
        user="$SERVICE_USER"
    fi

    ui_soft_clear
    # subtitle: path · version (single-width separators only)
    ui_banner "systemd ctl" "${app}  ${UI_DOT}  ${ver}"

    printf '\n'
    ui_kv "User" "$user"
    printf '\n'

    ui_section "Установка"
    ui_menu_item "1" "Установить / починить" "venv · Redis · units"

    ui_section "Обновление"
    ui_menu_item "2" "Релиз (stable)" "GitHub Release ${UI_STAR}"
    ui_menu_item "3" "Коммит (edge)" "ветка main"

    ui_section "Службы"
    ui_menu_item "4" "Перезапустить" "быстрый restart"
    ui_menu_item "5" "Статус" "telegram · web · Redis"
    ui_menu_item "6" "Логи" "live · q — назад"

    ui_section "Опасная зона"
    ui_menu_item "7" "Остановить"
    ui_menu_item "8" "Удалить службы" "только systemd units"
    ui_menu_item "9" "Снести бота полностью" "units · каталог · user"

    printf '\n'
    ui_menu_item "0" "Выход"
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
        ui_prompt "0-9"
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
                ui_header "Логи — q вернуться в меню"
                # без run_action «Готово» поверх live-view: вызываем напрямую
                echo
                if follow_all_logs; then
                    :
                else
                    err "Не удалось открыть логи"
                fi
                pause_menu
                ;;
            7)
                ui_header "Остановка служб"
                run_action stop_services
                pause_menu
                ;;
            8)
                printf '\n  %sУдалить systemd unit-файлы?%s [' "$C_YELLOW" "$C_RESET"
                printf '%sy/N%s]: ' "$C_BOLD" "$C_RESET"
                read -r confirm </dev/tty
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    run_action uninstall_services
                else
                    log "Отменено"
                fi
                pause_menu
                ;;
            9)
                ui_header "Полный снос бота"
                if cmd_purge_bot; then
                    printf '\n  %sВыход из меню — каталога уже нет.%s\n\n' "$C_DIM" "$C_RESET"
                    exit 0
                fi
                pause_menu
                ;;
            0|q|Q)
                printf '\n  %sПока.%s\n\n' "$C_DIM" "$C_RESET"
                exit 0
                ;;
            *)
                err "Введите число от 0 до 9"
                sleep 1
                ;;
        esac
    done
}

print_help() {
    cat <<EOF
${C_BOLD}${C_CYAN}VPN Bot${C_RESET} — systemd CLI ${C_DIM}(Charm-стиль, NO_COLOR=1 отключает цвета)${C_RESET}

  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh${C_RESET}                 меню
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh install${C_RESET}         окружение (+ Redis)
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh update${C_RESET}          последний Release (stable)
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh update --edge${C_RESET}   последний коммит main
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh restart|status|logs|stop|uninstall${C_RESET}
  ${C_GREEN}sudo bash deploy/vpn-bot-ctl.sh purge${C_RESET}           полный снос (нужно ввести DELETE)

Обновление без локального .git. Сохраняются: .env, data/, .venv/

Установка с нуля (мастер):
  curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh \\
    | sudo bash

Только код (без мастера):
  curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \\
    | sudo bash -s -- /opt/vpn-bot
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
            ui_banner "install" "окружение · Redis · units"
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

  sudo bash deploy/vpn-bot-ctl.sh update           # Release (stable)
  sudo bash deploy/vpn-bot-ctl.sh update --edge    # коммит main
EOF
                        return 0
                        ;;
                    *) die "Неизвестный флаг update: $1" ;;
                esac
                shift
            done
            require_root
            if [[ "$mode" == "edge" ]]; then
                ui_banner "update" "edge · последний коммит"
                cmd_update_bot_edge
            else
                ui_banner "update" "stable · последний Release"
                cmd_update_bot_release
            fi
            ;;
        update-release)
            require_root
            ui_banner "update" "stable"
            cmd_update_bot_release
            ;;
        update-edge|pull)
            require_root
            ui_banner "update" "edge"
            cmd_update_bot_edge
            ;;
        restart)
            require_root
            ui_banner "restart" "службы"
            restart_services
            ;;
        status)
            load_config 2>/dev/null || true
            ui_banner "status" "${APP_DIR:-?}  ${UI_DOT}  $(format_installed_version 2>/dev/null || echo '?')"
            show_status
            ;;
        logs|tail)
            require_root
            follow_all_logs
            ;;
        stop)
            require_root
            ui_banner "stop" "службы"
            stop_services
            ;;
        uninstall)
            require_root
            ui_banner "uninstall" "unit-файлы"
            uninstall_services
            ;;
        purge|destroy)
            require_root
            ui_banner "purge" "полный снос"
            cmd_purge_bot
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

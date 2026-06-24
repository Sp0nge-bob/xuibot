#!/usr/bin/env bash
# VPN Bot — управление systemd (меню 5 пунктов).
#
#   sudo bash deploy/vpn-bot-ctl.sh
#
# Пункт 1: установить / обновить / починить всё (идемпотентно).

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
# shellcheck source=lib/reconcile.sh
source "$DEPLOY_DIR/lib/reconcile.sh"

pause_menu() {
    echo
    read -r -p "Enter — вернуться в меню…" _ </dev/tty
}

draw_menu() {
    printf '\n'
    printf '%s\n' '╔══════════════════════════════════════════╗'
    printf '%s\n' '║       VPN Bot — управление systemd       ║'
    printf '%s\n' '╠══════════════════════════════════════════╣'
    printf '%s\n' '║  1) Установить / обновить службы         ║'
    printf '%s\n' '║  2) Проверить состояние служб            ║'
    printf '%s\n' '║  3) Остановить systemd службы            ║'
    printf '%s\n' '║  4) Удалить systemd службы               ║'
    printf '%s\n' '║  5) Выход                                ║'
    printf '%s\n' '╚══════════════════════════════════════════╝'
    printf '\n'
}

run_action() {
    if ( "$@" ); then
        return 0
    fi
    warn "Действие завершилось с ошибкой"
    return 1
}

interactive_menu() {
    require_root
    local choice

    while true; do
        draw_menu
        read -r -p 'Выберите пункт [1-5]: ' choice </dev/tty

        case "$choice" in
            1)
                echo
                log "Установка / обновление / починка…"
                run_action cmd_reconcile
                pause_menu
                ;;
            2)
                load_config 2>/dev/null || true
                show_status
                pause_menu
                ;;
            3)
                run_action stop_services
                pause_menu
                ;;
            4)
                read -r -p "Удалить службы? [y/N]: " confirm </dev/tty
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    run_action uninstall_services
                else
                    log "Отменено"
                fi
                pause_menu
                ;;
            5)
                exit 0
                ;;
            *)
                warn "Введите число 1–5"
                pause_menu
                ;;
        esac
    done
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        ""|menu)
            interactive_menu
            ;;
        install|reconcile)
            cmd_reconcile
            ;;
        status)
            load_config 2>/dev/null || true
            show_status
            ;;
        stop)
            require_root
            stop_services
            ;;
        uninstall)
            require_root
            uninstall_services
            ;;
        -h|--help)
            cat <<'EOF'
VPN Bot — systemd

  sudo bash deploy/vpn-bot-ctl.sh          # меню
  sudo bash deploy/vpn-bot-ctl.sh install  # установить / обновить
  sudo bash deploy/vpn-bot-ctl.sh status
  sudo bash deploy/vpn-bot-ctl.sh stop
  sudo bash deploy/vpn-bot-ctl.sh uninstall
EOF
            ;;
        *)
            die "Неизвестная команда: $cmd (см. --help)"
            ;;
    esac
}

main "$@"
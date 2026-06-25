#!/usr/bin/env bash
# VPN Bot — управление systemd (интерактивное меню).
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
# shellcheck source=lib/logs.sh
source "$DEPLOY_DIR/lib/logs.sh"
# shellcheck source=lib/redis.sh
source "$DEPLOY_DIR/lib/redis.sh"

pause_menu() {
    echo
    read -r -p "Enter — вернуться в меню…" _ </dev/tty
}

draw_menu() {
    printf '\n'
    printf '%s\n' '╔══════════════════════════════════════════╗'
    printf '%s\n' '║       VPN Bot — управление systemd       ║'
    printf '%s\n' '╠══════════════════════════════════════════╣'
    printf '%s\n' '║  1) Установить / обновить (+ Redis)      ║'
    printf '%s\n' '║  2) Перезапустить службы (быстро)        ║'
    printf '%s\n' '║  3) Проверить состояние служб            ║'
    printf '%s\n' '║  4) Логи в реальном времени              ║'
    printf '%s\n' '║  5) Остановить systemd службы            ║'
    printf '%s\n' '║  6) Удалить systemd службы               ║'
    printf '%s\n' '║  0) Выход                                ║'
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
        read -r -p 'Выберите пункт [0-6]: ' choice </dev/tty

        case "$choice" in
            1)
                echo
                log "Установка / обновление / починка…"
                run_action cmd_reconcile
                pause_menu
                ;;
            2)
                echo
                run_action restart_services
                pause_menu
                ;;
            3)
                load_config 2>/dev/null || true
                show_status
                pause_menu
                ;;
            4)
                run_action follow_all_logs
                pause_menu
                ;;
            5)
                run_action stop_services
                pause_menu
                ;;
            6)
                read -r -p "Удалить службы? [y/N]: " confirm </dev/tty
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    run_action uninstall_services
                else
                    log "Отменено"
                fi
                pause_menu
                ;;
            0)
                exit 0
                ;;
            *)
                warn "Введите 0 или число 1–6"
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
        restart)
            require_root
            restart_services
            ;;
        status)
            load_config 2>/dev/null || true
            show_status
            ;;
        logs|tail)
            require_root
            follow_all_logs
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
  sudo bash deploy/vpn-bot-ctl.sh install  # установить / обновить (+ redis-server)
  sudo bash deploy/vpn-bot-ctl.sh restart  # быстрый перезапуск служб
  sudo bash deploy/vpn-bot-ctl.sh status
  sudo bash deploy/vpn-bot-ctl.sh logs     # tail -f data/logs/bot.log
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
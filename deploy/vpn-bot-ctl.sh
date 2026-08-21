#!/usr/bin/env bash
# VPN Bot — управление systemd (интерактивное меню).
#
#   sudo bash deploy/vpn-bot-ctl.sh
#
# Пункт 1: установить / обновить / починить всё (идемпотентно).
# Пункт 2: обновить до последнего GitHub Release (stable).
# Пункт 3: обновить до последнего коммита main (edge).

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
    read -r -p "Enter — вернуться в меню…" _ </dev/tty
}

draw_menu() {
    local ver="неизвестно"
    if load_config 2>/dev/null; then
        ver="$(format_installed_version 2>/dev/null || echo неизвестно)"
    fi
    printf '\n'
    printf '%s\n' '╔══════════════════════════════════════════════╗'
    printf '%s\n' '║     VPN Bot — управление systemd             ║'
    printf '%s\n' "║  Сейчас: $(printf '%-33s' "$ver")║"
    printf '%s\n' '╠══════════════════════════════════════════════╣'
    printf '%s\n' '║  1) Установить / починить (+ Redis)          ║'
    printf '%s\n' '║  2) Обновить до последнего релиза (stable)   ║'
    printf '%s\n' '║  3) Обновить до последнего коммита (edge)    ║'
    printf '%s\n' '║  4) Перезапустить службы (быстро)            ║'
    printf '%s\n' '║  5) Проверить состояние служб                ║'
    printf '%s\n' '║  6) Логи в реальном времени                  ║'
    printf '%s\n' '║  7) Остановить systemd службы                ║'
    printf '%s\n' '║  8) Удалить systemd службы                   ║'
    printf '%s\n' '║  0) Выход                                    ║'
    printf '%s\n' '╚══════════════════════════════════════════════╝'
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
        read -r -p 'Выберите пункт [0-8]: ' choice </dev/tty

        case "$choice" in
            1)
                echo
                log "Установка / обновление / починка…"
                run_action cmd_reconcile
                pause_menu
                ;;
            2)
                echo
                log "Stable: последний GitHub Release…"
                run_action cmd_update_bot_release
                pause_menu
                ;;
            3)
                echo
                log "Edge: последний коммит main…"
                run_action cmd_update_bot_edge
                pause_menu
                ;;
            4)
                echo
                run_action restart_services
                pause_menu
                ;;
            5)
                load_config 2>/dev/null || true
                show_status
                pause_menu
                ;;
            6)
                run_action follow_all_logs
                pause_menu
                ;;
            7)
                run_action stop_services
                pause_menu
                ;;
            8)
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
                warn "Введите 0 или число 1–8"
                pause_menu
                ;;
        esac
    done
}

main() {
    local cmd="${1:-}"
    shift || true
    case "$cmd" in
        ""|menu)
            interactive_menu
            ;;
        install|reconcile)
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
            if [[ "$mode" == "edge" ]]; then
                cmd_update_bot_edge
            else
                cmd_update_bot_release
            fi
            ;;
        update-release)
            cmd_update_bot_release
            ;;
        update-edge|pull)
            cmd_update_bot_edge
            ;;
        restart)
            require_root
            restart_services
            ;;
        status)
            load_config 2>/dev/null || true
            show_status
            if [[ -n "${APP_DIR:-}" ]]; then
                log "Версия: $(format_installed_version)"
            fi
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
VPN Bot — systemd CLI

  sudo bash deploy/vpn-bot-ctl.sh                 # меню
  sudo bash deploy/vpn-bot-ctl.sh install         # окружение (+ Redis)
  sudo bash deploy/vpn-bot-ctl.sh update          # последний Release (stable)
  sudo bash deploy/vpn-bot-ctl.sh update --edge   # последний коммит main
  sudo bash deploy/vpn-bot-ctl.sh update-release
  sudo bash deploy/vpn-bot-ctl.sh update-edge
  sudo bash deploy/vpn-bot-ctl.sh restart
  sudo bash deploy/vpn-bot-ctl.sh status
  sudo bash deploy/vpn-bot-ctl.sh logs
  sudo bash deploy/vpn-bot-ctl.sh stop
  sudo bash deploy/vpn-bot-ctl.sh uninstall

Обновление кода не требует локальный .git: скачивается архив с GitHub.
Сохраняются .env, data/, .venv/.
EOF
            ;;
        *)
            die "Неизвестная команда: $cmd (см. --help)"
            ;;
    esac
}

main "$@"

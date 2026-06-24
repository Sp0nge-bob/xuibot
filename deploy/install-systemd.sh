#!/usr/bin/env bash
# Интерактивное управление systemd-сервисами vpn-bot-telegram и vpn-bot-web.
#
# Меню (на VPS, от root):
#   sudo bash deploy/install-systemd.sh
#
# Неинтерактивно:
#   sudo bash deploy/install-systemd.sh install
#   sudo bash deploy/install-systemd.sh status
#   sudo bash deploy/install-systemd.sh stop
#   sudo bash deploy/install-systemd.sh uninstall
#
# Переменные окружения:
#   APP_DIR, SERVICE_USER, PYTHON_BIN, ENABLE_ON_BOOT=1, START_NOW=1, CREATE_USER=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

APP_DIR="${APP_DIR:-}"
SERVICE_USER="${SERVICE_USER:-vpnbot}"
PYTHON_BIN="${PYTHON_BIN:-}"
ENABLE_ON_BOOT="${ENABLE_ON_BOOT:-1}"
START_NOW="${START_NOW:-1}"
CREATE_USER="${CREATE_USER:-1}"

TELEGRAM_UNIT="vpn-bot-telegram.service"
WEB_UNIT="vpn-bot-web.service"

log() { printf '==> %s\n' "$*"; }
warn() { printf '!! %s\n' "$*" >&2; }
ok() { printf '✓ %s\n' "$*"; }

die() {
    warn "$*"
    exit 1
}

usage() {
    cat <<'EOF'
VPN Bot — управление systemd-сервисами

Интерактивное меню:
  sudo bash deploy/install-systemd.sh

Команды:
  install     Установить/обновить unit-файлы и запустить
  status      Проверить состояние служб
  stop        Остановить службы (без удаления)
  uninstall   Остановить, отключить и удалить unit-файлы

Опции:
  -d, --app-dir PATH     Каталог проекта
  -u, --user NAME        Пользователь systemd (по умолчанию: vpnbot)
  -p, --python PATH      Python из venv
      --no-create-user   Не создавать пользователя
      --no-enable        Не включать автозапуск
      --no-start         Не запускать сервисы после установки
  -h, --help             Справка
EOF
}

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        die "Запустите от root: sudo bash deploy/install-systemd.sh"
    fi
}

normalize_path() {
    local path="$1"
    if command -v realpath >/dev/null 2>&1; then
        realpath "$path"
    else
        (cd "$path" && pwd -P)
    fi
}

default_app_dir() {
    if [[ -d /opt/vpn-bot ]]; then
        echo /opt/vpn-bot
    else
        echo "$REPO_ROOT"
    fi
}

parse_args() {
    local cmd=""
    if [[ $# -gt 0 && "$1" != -* ]]; then
        cmd="$1"
        shift
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            install|uninstall|status|stop|menu)
                cmd="$1"
                shift
                ;;
            -d|--app-dir)
                [[ $# -ge 2 ]] || die "Опция $1 требует значение"
                APP_DIR="$2"
                shift 2
                ;;
            -u|--user)
                [[ $# -ge 2 ]] || die "Опция $1 требует значение"
                SERVICE_USER="$2"
                shift 2
                ;;
            -p|--python)
                [[ $# -ge 2 ]] || die "Опция $1 требует значение"
                PYTHON_BIN="$2"
                shift 2
                ;;
            --no-create-user)
                CREATE_USER=0
                shift
                ;;
            --no-enable)
                ENABLE_ON_BOOT=0
                shift
                ;;
            --no-start)
                START_NOW=0
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                die "Неизвестный аргумент: $1 (см. --help)"
                ;;
        esac
    done

    COMMAND="$cmd"
}

resolve_paths() {
    if [[ -z "$APP_DIR" ]]; then
        APP_DIR="$(default_app_dir)"
    fi
    [[ -d "$APP_DIR" ]] || die "Каталог проекта не найден: $APP_DIR"
    APP_DIR="$(normalize_path "$APP_DIR")"

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="$APP_DIR/.venv/bin/python"
    fi
    PYTHON_BIN="$(normalize_path "$PYTHON_BIN" 2>/dev/null || echo "$PYTHON_BIN")"
    VENV_BIN="$(dirname "$PYTHON_BIN")"
}

validate_project() {
    [[ -f "$APP_DIR/app.py" ]] || die "Не найден $APP_DIR/app.py"
    [[ -f "$APP_DIR/run_bot.py" ]] || die "Не найден $APP_DIR/run_bot.py"
    [[ -x "$PYTHON_BIN" ]] || die "Python не найден или не исполняемый: $PYTHON_BIN"
}

ensure_service_user() {
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        log "Пользователь $SERVICE_USER уже существует"
        return
    fi

    if [[ "$CREATE_USER" != "1" ]]; then
        die "Пользователь $SERVICE_USER не существует (создайте вручную или уберите --no-create-user)"
    fi

    log "Создаём системного пользователя $SERVICE_USER"
    useradd -r -d "$APP_DIR" -s /usr/sbin/nologin "$SERVICE_USER"
}

fix_permissions() {
    log "Права на $APP_DIR для $SERVICE_USER"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

    if [[ -f "$APP_DIR/.env" ]]; then
        chmod 600 "$APP_DIR/.env"
        chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
    fi
}

write_unit() {
    local name="$1"
    local program="$2"
    local dst="$SYSTEMD_DIR/$name"

    log "Записываем $dst"

    if [[ "$name" == "$WEB_UNIT" ]]; then
        cat >"$dst" <<EOF
[Unit]
Description=VPN Bot Webhook (Platega + fulfillment queue)
After=network.target $TELEGRAM_UNIT
Wants=$TELEGRAM_UNIT

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_BIN
ExecStartPre=/bin/sleep 8
ExecStart=$PYTHON_BIN $program
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    else
        cat >"$dst" <<EOF
[Unit]
Description=VPN Bot Telegram (polling + scheduler)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment=PATH=$VENV_BIN
ExecStart=$PYTHON_BIN $program
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    fi

    chmod 644 "$dst"
}

install_units() {
    write_unit "$TELEGRAM_UNIT" "run_bot.py"
    write_unit "$WEB_UNIT" "app.py"

    log "systemctl daemon-reload"
    systemctl daemon-reload

    if [[ "$ENABLE_ON_BOOT" == "1" ]]; then
        log "Включаем автозапуск"
        systemctl enable "$TELEGRAM_UNIT" "$WEB_UNIT"
    fi

    if [[ "$START_NOW" == "1" ]]; then
        log "Запускаем сервисы (сначала Telegram, затем webhook)"
        systemctl restart "$TELEGRAM_UNIT"
        systemctl restart "$WEB_UNIT"
    fi
}

stop_units() {
    log "Останавливаем сервисы"
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    ok "Службы остановлены"
}

uninstall_units() {
    log "Останавливаем и отключаем сервисы"
    systemctl disable --now "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$TELEGRAM_UNIT" "$SYSTEMD_DIR/$WEB_UNIT"
    systemctl daemon-reload
    ok "Unit-файлы удалены"
}

show_status() {
    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "vpn-bot-telegram"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if systemctl is-active --quiet "$TELEGRAM_UNIT" 2>/dev/null; then
        ok "active"
    elif systemctl list-unit-files "$TELEGRAM_UNIT" 2>/dev/null | grep -q "$TELEGRAM_UNIT"; then
        warn "inactive или ошибка"
    else
        warn "не установлен"
    fi
    systemctl --no-pager status "$TELEGRAM_UNIT" 2>/dev/null || true

    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "vpn-bot-web"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    if systemctl is-active --quiet "$WEB_UNIT" 2>/dev/null; then
        ok "active"
    elif systemctl list-unit-files "$WEB_UNIT" 2>/dev/null | grep -q "$WEB_UNIT"; then
        warn "inactive или ошибка"
    else
        warn "не установлен"
    fi
    systemctl --no-pager status "$WEB_UNIT" 2>/dev/null || true
    echo
}

cmd_install() {
    require_root
    resolve_paths
    validate_project
    ensure_service_user
    fix_permissions
    install_units
    show_status
    ok "Установка завершена"
}

cmd_stop() {
    require_root
    stop_units
}

cmd_uninstall() {
    require_root
    uninstall_units
}

cmd_status() {
    show_status
}

prompt_install_settings() {
    local default_dir default_user
    default_dir="$(default_app_dir)"
    default_user="vpnbot"

    echo
    read -r -p "Каталог проекта [$default_dir]: " input_dir
    APP_DIR="${input_dir:-$default_dir}"

    read -r -p "Пользователь systemd [$default_user]: " input_user
    SERVICE_USER="${input_user:-$default_user}"

    PYTHON_BIN=""
    ENABLE_ON_BOOT=1
    START_NOW=1
    CREATE_USER=1
}

pause_menu() {
    echo
    read -r -p "Нажмите Enter, чтобы вернуться в меню…" _
}

draw_menu() {
    printf '\n'
    printf '%s\n' '╔══════════════════════════════════════════╗'
    printf '%s\n' '║       VPN Bot — управление systemd       ║'
    printf '%s\n' '╠══════════════════════════════════════════╣'
    printf '%s\n' '║  1) Установить systemd службы            ║'
    printf '%s\n' '║  2) Проверить состояние служб            ║'
    printf '%s\n' '║  3) Остановить systemd службы            ║'
    printf '%s\n' '║  4) Удалить systemd службы               ║'
    printf '%s\n' '║  5) Выход                                ║'
    printf '%s\n' '╚══════════════════════════════════════════╝'
    printf '\n'
}

interactive_menu() {
    require_root
    local choice

    while true; do
        draw_menu
        read -r -p 'Выберите пункт [1-5]: ' choice

        case "$choice" in
            1)
                prompt_install_settings
                if (cmd_install); then
                    ok "Готово"
                else
                    warn "Установка не выполнена"
                fi
                pause_menu
                ;;
            2)
                cmd_status
                pause_menu
                ;;
            3)
                set +e
                cmd_stop
                set -e
                pause_menu
                ;;
            4)
                echo
                read -r -p "Удалить unit-файлы и отключить автозапуск? [y/N]: " confirm
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    set +e
                    cmd_uninstall
                    set -e
                else
                    log "Отменено"
                fi
                pause_menu
                ;;
            5)
                log "Выход"
                exit 0
                ;;
            *)
                warn "Неверный пункт. Введите число от 1 до 5."
                pause_menu
                ;;
        esac
    done
}

main() {
    parse_args "$@"

    if [[ -z "${COMMAND:-}" ]]; then
        interactive_menu
        return
    fi

    case "$COMMAND" in
        install)
            [[ -n "$APP_DIR" ]] || APP_DIR="$(default_app_dir)"
            cmd_install
            ;;
        status)
            cmd_status
            ;;
        stop)
            cmd_stop
            ;;
        uninstall)
            cmd_uninstall
            ;;
        menu)
            interactive_menu
            ;;
        *)
            die "Неизвестная команда: $COMMAND (см. --help)"
            ;;
    esac
}

main "$@"
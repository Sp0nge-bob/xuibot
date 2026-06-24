#!/usr/bin/env bash
# Установка systemd-сервисов vpn-bot-telegram и vpn-bot-web.
#
# Использование (на VPS, от root):
#   sudo bash deploy/install-systemd.sh
#   sudo bash deploy/install-systemd.sh --app-dir /opt/vpn-bot --user vpnbot
#   sudo bash deploy/install-systemd.sh uninstall
#
# Переменные окружения (альтернатива флагам):
#   APP_DIR, SERVICE_USER, PYTHON_BIN, ENABLE_ON_BOOT=1, START_NOW=1, CREATE_USER=1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

APP_DIR="${APP_DIR:-$REPO_ROOT}"
SERVICE_USER="${SERVICE_USER:-vpnbot}"
PYTHON_BIN="${PYTHON_BIN:-}"
ENABLE_ON_BOOT="${ENABLE_ON_BOOT:-1}"
START_NOW="${START_NOW:-1}"
CREATE_USER="${CREATE_USER:-1}"

TELEGRAM_UNIT="vpn-bot-telegram.service"
WEB_UNIT="vpn-bot-web.service"

log() { printf '==> %s\n' "$*"; }
warn() { printf '!! %s\n' "$*" >&2; }
die() { warn "$*"; exit 1; }

usage() {
    cat <<'EOF'
VPN Bot — установка systemd-сервисов

Команды:
  install     Установить/обновить unit-файлы (по умолчанию)
  uninstall   Остановить, отключить и удалить unit-файлы
  status      Показать статус сервисов

Опции:
  -d, --app-dir PATH     Каталог проекта (по умолчанию: корень репозитория)
  -u, --user NAME        Пользователь systemd (по умолчанию: vpnbot)
  -p, --python PATH      Python из venv (по умолчанию: APP_DIR/.venv/bin/python)
      --no-create-user   Не создавать пользователя
      --no-enable        Не включать автозапуск
      --no-start         Не запускать сервисы после установки
  -h, --help             Справка

Примеры:
  sudo bash deploy/install-systemd.sh
  sudo bash deploy/install-systemd.sh -d /opt/vpn-bot -u vpnbot
  sudo APP_DIR=/opt/vpn-bot bash deploy/install-systemd.sh install
  sudo bash deploy/install-systemd.sh uninstall
EOF
}

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        die "Запустите скрипт от root: sudo bash deploy/install-systemd.sh"
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

parse_args() {
    local cmd="install"
    if [[ $# -gt 0 && "$1" != -* ]]; then
        cmd="$1"
        shift
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            install|uninstall|status)
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
    local extra_after="${3:-}"
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
After=network.target$extra_after

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

uninstall_units() {
    log "Останавливаем и отключаем сервисы"
    systemctl disable --now "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$TELEGRAM_UNIT" "$SYSTEMD_DIR/$WEB_UNIT"
    systemctl daemon-reload
    log "Unit-файлы удалены"
}

show_status() {
    systemctl --no-pager status "$TELEGRAM_UNIT" "$WEB_UNIT" 2>/dev/null || true
}

main() {
    parse_args "$@"

    case "${COMMAND:-install}" in
        install)
            require_root
            resolve_paths
            validate_project
            ensure_service_user
            fix_permissions
            install_units
            show_status
            log "Готово"
            ;;
        uninstall)
            require_root
            uninstall_units
            ;;
        status)
            show_status
            ;;
        *)
            die "Неизвестная команда: ${COMMAND}"
            ;;
    esac
}

main "$@"
#!/usr/bin/env bash
# Интерактивное управление systemd-сервисами vpn-bot-telegram и vpn-bot-web.
#
#   sudo bash deploy/install-systemd.sh
#
# Пункт 1 делает всё сам: venv, pip install, пользователь vpnbot, unit-файлы, запуск.

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

  sudo bash deploy/install-systemd.sh

Команды (неинтерактивно):
  install | status | stop | uninstall
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

detect_app_dir() {
    if [[ -n "$APP_DIR" ]]; then
        echo "$APP_DIR"
        return
    fi
    if [[ -f "$REPO_ROOT/app.py" && -f "$REPO_ROOT/run_bot.py" ]]; then
        echo "$REPO_ROOT"
        return
    fi
    if [[ -d /opt/vpn-bot && -f /opt/vpn-bot/app.py ]]; then
        echo /opt/vpn-bot
        return
    fi
    echo "$REPO_ROOT"
}

auto_configure_install() {
    APP_DIR="$(detect_app_dir)"
    SERVICE_USER="vpnbot"
    PYTHON_BIN=""
    ENABLE_ON_BOOT=1
    START_NOW=1
    CREATE_USER=1
}

resolve_paths() {
    [[ -d "$APP_DIR" ]] || die "Каталог проекта не найден: $APP_DIR"
    APP_DIR="$(normalize_path "$APP_DIR")"

    if [[ -z "$PYTHON_BIN" ]]; then
        PYTHON_BIN="$APP_DIR/.venv/bin/python"
    fi
    if [[ -x "$PYTHON_BIN" ]]; then
        PYTHON_BIN="$(normalize_path "$PYTHON_BIN")"
    fi
    VENV_BIN="$APP_DIR/.venv/bin"
}

find_system_python() {
    local c
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

ensure_os_python_venv() {
    local py_cmd="$1"
    local probe
    probe="$(mktemp -d /tmp/vpnbot-venv-probe.XXXXXX)"
    if "$py_cmd" -m venv "$probe" >/dev/null 2>&1; then
        rm -rf "$probe"
        return 0
    fi
    rm -rf "$probe" 2>/dev/null || true

    warn "Пакет python3-venv не найден — ставим через apt"
    if ! command -v apt-get >/dev/null 2>&1; then
        die "Установите python3-venv для $py_cmd и запустите скрипт снова"
    fi
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y python3-venv python3-pip \
        python3.11-venv python3.12-venv 2>/dev/null \
        || apt-get install -y python3-venv python3-pip
}

ensure_env_file() {
    if [[ -f "$APP_DIR/.env" ]]; then
        return
    fi
    [[ -f "$APP_DIR/.env.example" ]] || die "Нет $APP_DIR/.env — скопируйте .env.example в .env и заполните"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    warn "Создан $APP_DIR/.env из .env.example — проверьте секреты перед продакшеном"
}

fix_env_for_systemd() {
    local env_file="$APP_DIR/.env"
    if grep -Eq '^[[:space:]]*START_BOT_IN_WEBAPP[[:space:]]*=[[:space:]]*true' "$env_file"; then
        log "В .env выключаем START_BOT_IN_WEBAPP (нужно false для двух сервисов)"
        sed -i 's/^[[:space:]]*START_BOT_IN_WEBAPP[[:space:]]*=.*/START_BOT_IN_WEBAPP=false/' "$env_file"
    fi
}

validate_project() {
    [[ -f "$APP_DIR/app.py" ]] || die "Не найден $APP_DIR/app.py"
    [[ -f "$APP_DIR/run_bot.py" ]] || die "Не найден $APP_DIR/run_bot.py"
    [[ -f "$APP_DIR/pyproject.toml" ]] || die "Не найден $APP_DIR/pyproject.toml"
    ensure_env_file
    fix_env_for_systemd
}

ensure_service_user() {
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        log "Пользователь $SERVICE_USER уже существует"
        return
    fi
    if [[ "$CREATE_USER" != "1" ]]; then
        die "Пользователь $SERVICE_USER не существует"
    fi
    log "Создаём пользователя $SERVICE_USER"
    useradd -r -d "$APP_DIR" -s /usr/sbin/nologin "$SERVICE_USER"
}

ensure_venv() {
    local venv_py="$APP_DIR/.venv/bin/python"
    if [[ -x "$venv_py" ]]; then
        PYTHON_BIN="$venv_py"
        return
    fi

    local py_cmd
    py_cmd="$(find_system_python)" || die "Python 3.11+ не найден"

    ensure_os_python_venv "$py_cmd"
    log "Создаём virtualenv: $APP_DIR/.venv"
    "$py_cmd" -m venv "$APP_DIR/.venv"
    PYTHON_BIN="$venv_py"
    [[ -x "$PYTHON_BIN" ]] || die "Не удалось создать venv"
}

fix_permissions() {
    log "Права на $APP_DIR → $SERVICE_USER"
    mkdir -p "$APP_DIR/data/logs"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
    if [[ -f "$APP_DIR/.env" ]]; then
        chmod 600 "$APP_DIR/.env"
        chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
    fi
}

python_deps_ok() {
    sudo -u "$SERVICE_USER" env \
        PATH="$VENV_BIN:$PATH" \
        VIRTUAL_ENV="$APP_DIR/.venv" \
        "$PYTHON_BIN" -c "import aiogram, fastapi, loguru" 2>/dev/null
}

ensure_python_deps() {
    log "Проверяем зависимости Python"
    if python_deps_ok; then
        ok "Зависимости уже установлены"
        return
    fi
    log "Устанавливаем зависимости (pip install -e .) — может занять 1–3 мин"
    sudo -u "$SERVICE_USER" env \
        PATH="$VENV_BIN:$PATH" \
        VIRTUAL_ENV="$APP_DIR/.venv" \
        "$PYTHON_BIN" -m pip install -U pip wheel
    sudo -u "$SERVICE_USER" env \
        PATH="$VENV_BIN:$PATH" \
        VIRTUAL_ENV="$APP_DIR/.venv" \
        "$PYTHON_BIN" -m pip install -e "$APP_DIR"
    python_deps_ok || die "Не удалось установить зависимости (проверьте интернет)"
    ok "Зависимости установлены"
}

stop_stray_bot_processes() {
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    pkill -f "$APP_DIR/run_bot.py" 2>/dev/null || true
    pkill -f "$APP_DIR/app.py" 2>/dev/null || true
    rm -f "$APP_DIR/data/.polling.lock"
}

write_unit() {
    local name="$1"
    local program="$2"
    local dst="$SYSTEMD_DIR/$name"

    log "Unit: $dst"

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
Environment=VIRTUAL_ENV=$APP_DIR/.venv
Environment=PATH=$VENV_BIN:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
ExecStartPre=/bin/sleep 8
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/$program
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
Environment=VIRTUAL_ENV=$APP_DIR/.venv
Environment=PATH=$VENV_BIN:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/$program
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    fi
    chmod 644 "$dst"
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

verify_services_after_start() {
    local failed=0
    if ! wait_for_service "$TELEGRAM_UNIT"; then
        warn "$TELEGRAM_UNIT не запустился"
        show_service_logs "$TELEGRAM_UNIT" 30
        failed=1
    else
        ok "$TELEGRAM_UNIT active"
    fi
    if ! wait_for_service "$WEB_UNIT"; then
        warn "$WEB_UNIT не запустился"
        show_service_logs "$WEB_UNIT" 30
        failed=1
    else
        ok "$WEB_UNIT active"
    fi
    return "$failed"
}

install_units() {
    stop_stray_bot_processes
    write_unit "$TELEGRAM_UNIT" "run_bot.py"
    write_unit "$WEB_UNIT" "app.py"
    systemctl daemon-reload
    systemctl enable "$TELEGRAM_UNIT" "$WEB_UNIT"
    log "Запускаем сервисы"
    systemctl restart "$TELEGRAM_UNIT"
    systemctl restart "$WEB_UNIT"
    verify_services_after_start
}

stop_units() {
    log "Останавливаем сервисы"
    systemctl stop "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    ok "Службы остановлены"
}

uninstall_units() {
    log "Удаляем сервисы"
    systemctl disable --now "$WEB_UNIT" "$TELEGRAM_UNIT" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/$TELEGRAM_UNIT" "$SYSTEMD_DIR/$WEB_UNIT"
    systemctl daemon-reload
    ok "Unit-файлы удалены"
}

unit_state_label() {
    local unit="$1"
    if ! systemctl cat "$unit" &>/dev/null; then
        warn "не установлен"
        return
    fi
    if systemctl is-active --quiet "$unit" 2>/dev/null; then
        ok "active"
    else
        warn "inactive / ошибка"
    fi
}

show_status() {
    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "vpn-bot-telegram"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    unit_state_label "$TELEGRAM_UNIT"
    systemctl --no-pager status "$TELEGRAM_UNIT" 2>/dev/null | head -n 12 || true

    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "vpn-bot-web"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    unit_state_label "$WEB_UNIT"
    systemctl --no-pager status "$WEB_UNIT" 2>/dev/null | head -n 12 || true
    echo
}

cmd_install() {
    require_root
    auto_configure_install
    log "Каталог: $APP_DIR"
    log "Пользователь: $SERVICE_USER"
    resolve_paths
    validate_project
    ensure_service_user
    ensure_venv
    resolve_paths
    fix_permissions
    ensure_python_deps
    install_units
    echo
    ok "Установка завершена"
    log "Проверка: curl -s http://127.0.0.1:8080/health"
    show_status
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

pause_menu() {
    echo
    read -r -p "Enter — вернуться в меню…" _ </dev/tty
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
        read -r -p 'Выберите пункт [1-5]: ' choice </dev/tty

        case "$choice" in
            1)
                echo
                log "Полная установка (venv, pip, systemd, запуск)…"
                if (cmd_install); then
                    ok "Готово — бот должен работать"
                else
                    warn "Установка завершилась с ошибкой — см. сообщения выше"
                fi
                pause_menu
                ;;
            2)
                cmd_status
                pause_menu
                ;;
            3)
                (cmd_stop) || warn "Не удалось остановить"
                pause_menu
                ;;
            4)
                read -r -p "Удалить службы? [y/N]: " confirm </dev/tty
                if [[ "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
                    (cmd_uninstall) || warn "Не удалось удалить"
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

parse_args() {
    local cmd=""
    if [[ $# -gt 0 && "$1" != -* ]]; then
        cmd="$1"
        shift
    fi
    while [[ $# -gt 0 ]]; do
        case "$1" in
            install|uninstall|status|stop|menu|-h|--help)
                [[ "$1" == "-h" || "$1" == "--help" ]] && { usage; exit 0; }
                [[ "$1" != "-h" && "$1" != "--help" ]] && cmd="$1"
                shift
                ;;
            -d|--app-dir)
                APP_DIR="$2"
                shift 2
                ;;
            *)
                die "Неизвестный аргумент: $1"
                ;;
        esac
    done
    COMMAND="$cmd"
}

main() {
    parse_args "$@"
    if [[ -z "${COMMAND:-}" ]]; then
        interactive_menu
        return
    fi
    case "$COMMAND" in
        install) cmd_install ;;
        status) cmd_status ;;
        stop) cmd_stop ;;
        uninstall) cmd_uninstall ;;
        menu) interactive_menu ;;
        *) die "Неизвестная команда: $COMMAND" ;;
    esac
}

main "$@"
# shellcheck shell=bash
# Общие функции: логи, пути, state.env

: "${DEPLOY_DIR:?}"
: "${REPO_ROOT:?}"

SYSTEMD_DIR="/etc/systemd/system"
TELEGRAM_UNIT="vpn-bot-telegram.service"
WEB_UNIT="vpn-bot-web.service"

APP_DIR="${APP_DIR:-}"
SERVICE_USER="${SERVICE_USER:-vpnbot}"
STATE_FILE="$DEPLOY_DIR/state.env"

# shellcheck source=ui.sh
source "$DEPLOY_DIR/lib/ui.sh"

# ASCII markers in logs — корректно в любом шрифте/locale (без «битых» ✓)
log()  { printf '%s==>%s %s\n' "${C_CYAN:-}" "${C_RESET:-}" "$*"; }
warn() { printf '%s!! %s%s\n' "${C_YELLOW:-}" "$*" "${C_RESET:-}" >&2; }
ok()   { printf '%sOK%s  %s\n' "${C_GREEN:-}" "${C_RESET:-}" "$*"; }
err()  { printf '%sERR%s %s\n' "${C_RED:-}" "$*" "${C_RESET:-}" >&2; }

die() {
    err "$*"
    exit 1
}

require_root() {
    if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
        die "Запустите от root: sudo bash deploy/vpn-bot-ctl.sh"
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
    if [[ -n "${APP_DIR:-}" ]]; then
        echo "$APP_DIR"
        return
    fi
    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
        source "$STATE_FILE"
        if [[ -n "${APP_DIR:-}" && -f "$APP_DIR/app.py" ]]; then
            echo "$APP_DIR"
            return
        fi
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

load_config() {
    APP_DIR="$(detect_app_dir)"
    [[ -d "$APP_DIR" ]] || die "Каталог проекта не найден: $APP_DIR"
    APP_DIR="$(normalize_path "$APP_DIR")"
    SERVICE_USER="${SERVICE_USER:-vpnbot}"
    VENV_BIN="$APP_DIR/.venv/bin"
    PYTHON_BIN="$VENV_BIN/python"
    if [[ "$APP_DIR" == /root/* ]]; then
        warn "Проект в $APP_DIR — для продакшена лучше /opt/vpn-bot (скрипт починит права /root)"
    fi
}

save_state() {
    mkdir -p "$DEPLOY_DIR"
    local git_remote=""
    if [[ -f "$STATE_FILE" ]]; then
        git_remote="$(grep -E '^GIT_REMOTE=' "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
    fi
    if [[ -n "${GIT_REMOTE:-}" ]]; then
        git_remote="$GIT_REMOTE"
    elif [[ -z "$git_remote" && -d "${APP_DIR:-}/.git" ]]; then
        git_remote="$(git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
    fi
    cat >"$STATE_FILE" <<EOF
# Автогенерация deploy/vpn-bot-ctl.sh — не редактируйте вручную
APP_DIR=$APP_DIR
SERVICE_USER=$SERVICE_USER
INSTALLED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF
    if [[ -n "$git_remote" ]]; then
        printf 'GIT_REMOTE=%s\n' "$git_remote" >>"$STATE_FILE"
    fi
    chmod 644 "$STATE_FILE"
    ok "Состояние сохранено: $STATE_FILE"
}

validate_project() {
    [[ -f "$APP_DIR/app.py" ]] || die "Не найден $APP_DIR/app.py"
    [[ -f "$APP_DIR/run_bot.py" ]] || die "Не найден $APP_DIR/run_bot.py"
    [[ -f "$APP_DIR/pyproject.toml" ]] || die "Не найден $APP_DIR/pyproject.toml"
}

ensure_env_file() {
    if [[ -f "$APP_DIR/.env" ]]; then
        return
    fi
    [[ -f "$APP_DIR/.env.example" ]] || die "Нет .env — скопируйте .env.example"
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    warn "Создан .env из .env.example — проверьте секреты"
}

fix_env_for_systemd() {
    local env_file="$APP_DIR/.env"
    if grep -Eq '^[[:space:]]*START_BOT_IN_WEBAPP[[:space:]]*=[[:space:]]*true' "$env_file"; then
        log "START_BOT_IN_WEBAPP=false (нужно для двух сервисов)"
        sed -i 's/^[[:space:]]*START_BOT_IN_WEBAPP[[:space:]]*=.*/START_BOT_IN_WEBAPP=false/' "$env_file"
    fi
}

ensure_service_user() {
    if id "$SERVICE_USER" >/dev/null 2>&1; then
        log "Пользователь $SERVICE_USER уже существует"
        return
    fi
    log "Создаём пользователя $SERVICE_USER"
    useradd -r -d "$APP_DIR" -s /usr/sbin/nologin "$SERVICE_USER"
}
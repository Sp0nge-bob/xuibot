#!/usr/bin/env bash
# =============================================================================
# VPN Shop Bot — установка одной командой (интерактивный мастер)
#
#   curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh \
#     | sudo bash
#
#   # или с путём:
#   curl -fsSL …/deploy/install.sh | sudo bash -s -- /opt/vpn-bot
#
# Канал кода: последний GitHub Release (stable).
# Сохраняет data/ и .venv/; .env создаётся/дополняется мастером.
# =============================================================================
set -euo pipefail

APP_DIR="${1:-/opt/vpn-bot}"
REMOTE="${GIT_REMOTE:-https://github.com/Sp0nge-bob/xuibot.git}"
BRANCH="${GIT_BRANCH:-main}"
SLUG="Sp0nge-bob/xuibot"
ENV_FILE=""
TTY="/dev/tty"

# ── UI ─────────────────────────────────────────────────────────
if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
    C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_DIM=$'\033[2m'
    C_CYAN=$'\033[36m' C_GREEN=$'\033[32m' C_YELLOW=$'\033[33m' C_RED=$'\033[31m'
else
    C_RESET="" C_BOLD="" C_DIM="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED=""
fi

case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8*|*utf8*|*UTF8*) _TL='╭' _TR='╮' _BL='╰' _BR='╯' _H='─' _V='│' ;;
    *)
        if locale charmap 2>/dev/null | grep -qi 'utf-8'; then
            _TL='╭' _TR='╮' _BL='╰' _BR='╯' _H='─' _V='│'
        else
            _TL='+' _TR='+' _BL='+' _BR='+' _H='-' _V='|'
        fi
        ;;
esac

log()  { printf '%s==>%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
ok()   { printf '%sOK%s  %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s!!%s  %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%sERR%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }
die()  { err "$*"; exit 1; }

banner() {
    local sub="${1:-install · мастер}"
    printf '\n%s%s' "$C_CYAN" "$_TL"
    printf '%s%s' "$_H$_H"
    printf '%s VPN Bot %s' "$C_RESET$C_BOLD" "$C_RESET$C_CYAN"
    local i=0; while [[ $i -lt 28 ]]; do printf '%s' "$_H"; i=$((i + 1)); done
    printf '%s%s\n' "$_TR" "$C_RESET"
    printf '%s%s%s  %s%-40s%s%s%s%s\n' \
        "$C_CYAN" "$_V" "$C_RESET" "$C_DIM" "$sub" "$C_RESET" "$C_CYAN" "$_V" "$C_RESET"
    printf '%s%s' "$C_CYAN" "$_BL"
    i=0; while [[ $i -lt 44 ]]; do printf '%s' "$_H"; i=$((i + 1)); done
    printf '%s%s\n\n' "$_BR" "$C_RESET"
}

# ── TTY (curl | bash) ──────────────────────────────────────────
ensure_tty() {
    if [[ ! -r "$TTY" ]]; then
        die "Нет $TTY (нужен интерактивный терминал). Скачайте скрипт и запустите: sudo bash install.sh"
    fi
}

ask() {
    # ask "Подсказка" "default" → пишет ответ в REPLY
    local prompt="$1" default="${2:-}"
    if [[ -n "$default" ]]; then
        printf '%s?%s %s %s[%s]%s: ' "$C_CYAN" "$C_RESET" "$prompt" "$C_DIM" "$default" "$C_RESET" >"$TTY"
    else
        printf '%s?%s %s: ' "$C_CYAN" "$C_RESET" "$prompt" >"$TTY"
    fi
    # shellcheck disable=SC2162
    IFS= read -r REPLY <"$TTY" || true
    if [[ -z "$REPLY" && -n "$default" ]]; then
        REPLY="$default"
    fi
}

ask_secret() {
    local prompt="$1"
    printf '%s?%s %s: ' "$C_CYAN" "$C_RESET" "$prompt" >"$TTY"
    # hide input when possible
    if stty -echo <"$TTY" 2>/dev/null; then
        IFS= read -r REPLY <"$TTY" || true
        stty echo <"$TTY" 2>/dev/null || true
        printf '\n' >"$TTY"
    else
        IFS= read -r REPLY <"$TTY" || true
    fi
}

ask_yn() {
    local prompt="$1" default="${2:-N}"
    ask "$prompt" "$default"
    case "${REPLY,,}" in
        y|yes|д|да) return 0 ;;
        *) return 1 ;;
    esac
}

# ── .env helpers (python — безопасно для спецсимволов) ─────────
env_set() {
    local key="$1" value="$2"
    ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
    KEY="$key" VALUE="$value" FILE="$ENV_FILE" python3 - <<'PY'
import os
from pathlib import Path
path = Path(os.environ["FILE"])
key = os.environ["KEY"]
value = os.environ["VALUE"]
lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

env_get() {
    local key="$1"
    [[ -f "$ENV_FILE" ]] || { echo ""; return; }
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

# ── Telegram getMe ─────────────────────────────────────────────
verify_bot_token() {
    local token="$1"
    local tmp resp
    tmp="$(mktemp)"
    if ! curl -fsSL --connect-timeout 15 --max-time 30 \
        -o "$tmp" "https://api.telegram.org/bot${token}/getMe"; then
        rm -f "$tmp"
        return 1
    fi
    resp="$(
        python3 - "$tmp" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not data.get("ok"):
    raise SystemExit(1)
r = data.get("result") or {}
print(r.get("username") or "")
print(r.get("id") or "")
print(r.get("first_name") or "")
PY
    )" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    BOT_USERNAME="$(printf '%s\n' "$resp" | sed -n '1p')"
    BOT_ID="$(printf '%s\n' "$resp" | sed -n '2p')"
    BOT_NAME="$(printf '%s\n' "$resp" | sed -n '3p')"
    [[ -n "$BOT_USERNAME" ]] || return 1
    return 0
}

# ── download code (stable release) ─────────────────────────────
slug_from_remote() {
    local r="$1"
    r="${r%.git}"; r="${r%/}"
    if [[ "$r" =~ github\.com[:/]+([^/]+)/([^/]+)$ ]]; then
        echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        return
    fi
    echo "$SLUG"
}

fetch_code() {
    local archive_url="" tag="" api tmp src
    SLUG="$(slug_from_remote "$REMOTE")"
    tmp="$(mktemp -d)"
    api="$(mktemp)"
    log "Скачиваю код (stable Release) → $APP_DIR"
    if curl -fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: vpn-bot-install" \
        -o "$api" "https://api.github.com/repos/${SLUG}/releases/latest"; then
        tag="$(python3 -c "import json;d=json.load(open('$api'));print(d.get('tag_name') or '')" 2>/dev/null || true)"
        if [[ -n "$tag" ]]; then
            archive_url="https://github.com/${SLUG}/archive/refs/tags/${tag}.tar.gz"
            log "Канал: stable · $tag"
        fi
    fi
    rm -f "$api"
    if [[ -z "$archive_url" ]]; then
        archive_url="https://github.com/${SLUG}/archive/refs/heads/${BRANCH}.tar.gz"
        warn "Релизов нет — ставлю ветку $BRANCH"
    fi
    curl -fsSL -o "$tmp/src.tar.gz" "$archive_url"
    mkdir -p "$tmp/extract"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp/extract"
    src="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [[ -f "$src/app.py" ]] || die "В архиве нет app.py"
    mkdir -p "$APP_DIR"
    # excludes из нового дерева (docs не копируем на VPS)
    # shellcheck source=/dev/null
    source "$src/deploy/lib/slim_excludes.sh"
    if command -v rsync >/dev/null 2>&1; then
        # shellcheck disable=SC2046
        rsync -a $(slim_rsync_exclude_args) "$src"/ "$APP_DIR"/
    else
        (cd "$src" && tar -cf - \
            --exclude='./.env' --exclude='./data' --exclude='./.venv' --exclude='./.git' \
            --exclude='./docs' --exclude='./report' --exclude='./scripts/dev' --exclude='./*.md' \
            . | tar -xf - -C "$APP_DIR")
    fi
    slim_purge_docs_from_app_dir "$APP_DIR"
    rm -rf "$tmp"
    chmod +x "$APP_DIR/deploy/"*.sh 2>/dev/null || true
    chmod +x "$APP_DIR/deploy/lib/"*.sh 2>/dev/null || true
    ok "Код разложен (без docs/report/*.md)"
}

# ── wizard ─────────────────────────────────────────────────────
run_wizard() {
    ENV_FILE="$APP_DIR/.env"
    local had_env=0
    if [[ -f "$ENV_FILE" ]]; then
        had_env=1
        warn "Найден существующий .env"
        if ! ask_yn "Обновить ключевые поля мастером? (N = оставить .env как есть)" "N"; then
            ok "Оставляем текущий .env"
            return 0
        fi
    else
        [[ -f "$APP_DIR/.env.example" ]] || die "Нет .env.example в $APP_DIR"
        cp "$APP_DIR/.env.example" "$ENV_FILE"
        ok "Создан .env из .env.example"
    fi

    # --- Telegram ---
    printf '\n%s▸ Telegram%s\n' "$C_BOLD" "$C_RESET"
    local token=""
    while true; do
        ask_secret "BOT_TOKEN (от @BotFather)"
        token="$(printf '%s' "$REPLY" | tr -d '[:space:]')"
        if [[ -z "$token" ]]; then
            warn "Токен пустой"
            continue
        fi
        log "Проверяю токен через api.telegram.org/getMe…"
        if verify_bot_token "$token"; then
            ok "Бот доступен: @${BOT_USERNAME} (id ${BOT_ID})"
            break
        fi
        warn "Токен не прошёл проверку getMe — проверьте и введите снова"
    done
    env_set "BOT_TOKEN" "$token"

    local admins
    ask "BOT_ADMINS (Telegram user id, через запятую)" "$(env_get BOT_ADMINS)"
    admins="$(printf '%s' "$REPLY" | tr -d ' ')"
    [[ -n "$admins" ]] || die "BOT_ADMINS обязателен"
    env_set "BOT_ADMINS" "$admins"

    ask "BOT_BRAND (название в меню)" "$(env_get BOT_BRAND)"
    [[ -n "$REPLY" ]] && env_set "BOT_BRAND" "$REPLY"

    # --- 3x-ui ---
    printf '\n%s▸ Панель 3x-ui (Primary)%s\n' "$C_BOLD" "$C_RESET"
    ask "XUI_HOST (HTTPS, secret path, БЕЗ /panel/)" "$(env_get XUI_HOST)"
    local host
    host="$(printf '%s' "$REPLY" | sed 's|/*$||')"
    [[ -n "$host" ]] || die "XUI_HOST обязателен"
    env_set "XUI_HOST" "$host"

    local use_token=1
    if ask_yn "Использовать API Token панели? (N = логин/пароль)" "Y"; then
        ask_secret "XUI_TOKEN"
        [[ -n "$REPLY" ]] || die "XUI_TOKEN пустой"
        env_set "XUI_TOKEN" "$REPLY"
        env_set "XUI_USERNAME" ""
        env_set "XUI_PASSWORD" ""
    else
        use_token=0
        ask "XUI_USERNAME" "$(env_get XUI_USERNAME)"
        env_set "XUI_USERNAME" "$REPLY"
        ask_secret "XUI_PASSWORD"
        env_set "XUI_PASSWORD" "$REPLY"
        env_set "XUI_TOKEN" ""
    fi

    ask "SUBSCRIPTION_BASE_URL (база ссылки подписки, Enter = пропустить)" "$(env_get SUBSCRIPTION_BASE_URL)"
    if [[ -n "$REPLY" ]]; then
        env_set "SUBSCRIPTION_BASE_URL" "$(printf '%s' "$REPLY" | sed 's|/*$||')/"
    fi

    # --- Platega / TEST_MODE ---
    printf '\n%s▸ Оплата%s\n' "$C_BOLD" "$C_RESET"
    if ask_yn "Настроить Platega сейчас? (N = TEST_MODE без реальных платежей)" "N"; then
        ask "PLATEGA_MERCHANT_ID" "$(env_get PLATEGA_MERCHANT_ID)"
        env_set "PLATEGA_MERCHANT_ID" "$REPLY"
        ask_secret "PLATEGA_SECRET"
        env_set "PLATEGA_SECRET" "$REPLY"
        ask "PUBLIC_WEBHOOK_URL (https://домен/platega-webhook)" "$(env_get PUBLIC_WEBHOOK_URL)"
        env_set "PUBLIC_WEBHOOK_URL" "$REPLY"
        env_set "TEST_MODE" "false"
        ok "Platega записана, TEST_MODE=false"
    else
        env_set "TEST_MODE" "true"
        # заглушки, чтобы pydantic не ругался на пустые
        local mid sec
        mid="$(env_get PLATEGA_MERCHANT_ID)"
        sec="$(env_get PLATEGA_SECRET)"
        if [[ -z "$mid" || "$mid" == *"xxxx"* ]]; then
            env_set "PLATEGA_MERCHANT_ID" "00000000-0000-0000-0000-000000000000"
        fi
        if [[ -z "$sec" || "$sec" == *"your_platega"* ]]; then
            env_set "PLATEGA_SECRET" "test-mode-placeholder"
        fi
        warn "TEST_MODE=true — оплата симулируется. Platega можно добавить позже в .env"
    fi

    env_set "START_BOT_IN_WEBAPP" "false"
    env_set "ALLOW_DEBUG_ADMIN" "false"
    ok "Конфигурация сохранена в $ENV_FILE"
    unset use_token
}

# ── main ───────────────────────────────────────────────────────
main() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Запустите от root: curl … | sudo bash"
    ensure_tty
    banner "install · мастер одной команды"

    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        log "Пакеты ОС (curl tar rsync python3)…"
        apt-get update -qq
        apt-get install -y curl ca-certificates tar rsync python3 python3-venv >/dev/null
    fi
    command -v curl >/dev/null || die "нужен curl"
    command -v python3 >/dev/null || die "нужен python3"

    log "Каталог установки: $APP_DIR"
    fetch_code
    run_wizard

    printf '\n'
    log "Запускаю полную установку (Redis, venv, systemd)…"
    # APP_DIR для ctl
    export APP_DIR
    if ! bash "$APP_DIR/deploy/vpn-bot-ctl.sh" install; then
        warn "ctl install завершился с ошибкой — проверьте .env и journalctl"
        warn "Повтор: sudo bash $APP_DIR/deploy/vpn-bot-ctl.sh  → пункт 1"
        exit 1
    fi

    printf '\n'
    ok "Установка завершена"
    printf '\n%sДальше:%s\n' "$C_BOLD" "$C_RESET"
    printf '  • Меню:     %ssudo bash %s/deploy/vpn-bot-ctl.sh%s\n' "$C_GREEN" "$APP_DIR" "$C_RESET"
    printf '  • Обновление: пункт 2 (stable) или 3 (edge)\n'
    printf '  • Health:   %scurl -s http://127.0.0.1:8080/health%s\n' "$C_DIM" "$C_RESET"
    printf '  • Webhook:  HTTPS + nginx → PUBLIC_WEBHOOK_URL (если не TEST_MODE)\n'
    if [[ "$(env_get TEST_MODE)" == "true" ]]; then
        printf '  • %sСейчас TEST_MODE=true%s — для прода пропишите Platega и TEST_MODE=false\n' "$C_YELLOW" "$C_RESET"
    fi
    if [[ -n "${BOT_USERNAME:-}" ]]; then
        printf '  • Бот:      %shttps://t.me/%s%s\n' "$C_CYAN" "$BOT_USERNAME" "$C_RESET"
    fi
    printf '\n'
}

main "$@"

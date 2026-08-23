#!/usr/bin/env bash
# =============================================================================
# VPN Shop Bot — установка одной командой (интерактивный мастер)
#
#   curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh \
#     | sudo bash
#
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
        if command -v locale >/dev/null 2>&1 && locale charmap 2>/dev/null | grep -qi 'utf-8'; then
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
        die "Нет $TTY (нужен интерактивный терминал). Скачайте скрипт и запустите: sudo bash install.sh [/opt/vpn-bot]"
    fi
}

_restore_tty_echo() {
    if [[ -r "$TTY" ]]; then
        stty echo <"$TTY" 2>/dev/null || true
        stty icanon <"$TTY" 2>/dev/null || true
    fi
}
trap '_restore_tty_echo' EXIT INT TERM

ask() {
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
    # Секретный ввод: символы не видны — обязательно предупреждаем
    local prompt="$1"
    printf '%s?%s %s\n' "$C_CYAN" "$C_RESET" "$prompt" >"$TTY"
    printf '  %s⚠  ВВОД СКРЫТ%s%s — на экране ничего не появляется (это нормально).%s\n' \
        "$C_YELLOW$C_BOLD" "$C_RESET" "$C_YELLOW" "$C_RESET" >"$TTY"
    printf '  %sВставьте токен/пароль из буфера и нажмите Enter.%s\n' \
        "$C_YELLOW" "$C_RESET" >"$TTY"
    printf '  %s> %s' "$C_DIM" "$C_RESET" >"$TTY"
    REPLY=""
    if stty -echo <"$TTY" 2>/dev/null; then
        # shellcheck disable=SC2162
        IFS= read -r REPLY <"$TTY" || true
        stty echo <"$TTY" 2>/dev/null || true
        printf '\n' >"$TTY"
    else
        warn "Не удалось скрыть ввод (stty) — токен будет ВИДЕН на экране"
        # shellcheck disable=SC2162
        IFS= read -r REPLY <"$TTY" || true
    fi
    if [[ -n "$REPLY" ]]; then
        printf '  %s✓ получено %s символов (содержимое скрыто)%s\n' \
            "$C_DIM" "${#REPLY}" "$C_RESET" >"$TTY"
    else
        printf '  %s(пусто — ничего не введено)%s\n' "$C_DIM" "$C_RESET" >"$TTY"
    fi
}

ask_yn() {
    local prompt="$1" default="${2:-N}" ans
    ask "$prompt" "$default"
    ans="$(printf '%s' "$REPLY" | tr '[:upper:]' '[:lower:]')"
    case "$ans" in
        y|yes|д|да) return 0 ;;
        *) return 1 ;;
    esac
}

# ── OS packages (прогресс + универсальные PM) ──────────────────
# Читает stdout/stderr команды и печатает ключевые строки + heartbeat при тишине.
_pm_filter() {
    local line st idle=0
    while true; do
        if IFS= read -r -t 3 line; then
            idle=0
            case "$line" in
                Get:*|Hit:*|Ign:*|Fetched\ *|Reading\ *|Building\ *|Unpacking\ *|Setting\ up\ *|Processing\ *|Selecting\ *|Preparing\ *|Created\ *|Synchronizing*|Downloading\ *|Installing\ *|Installed\ *|Verifying\ *|Running\ *|Transaction\ *|Dependencies\ *|Package\ *|Resolving\ *|Last\ metadata*|Complete!*|fetch\ *|OK:*|*\.deb*|*\.rpm*|  Installing*|  Upgrading*|  Verifying*|  Downloading*)
                    printf '  %s%s%s\n' "$C_DIM" "$line" "$C_RESET"
                    ;;
                *Err:*|*E:\ *|*error*|*Error*|*ERROR*|*FAILED*|*Failed*)
                    printf '  %s%s%s\n' "$C_RED" "$line" "$C_RESET"
                    ;;
            esac
        else
            st=$?
            if [[ "$st" -gt 128 ]]; then
                idle=$((idle + 3))
                printf '  %s… ещё работаю (%ss) — скачивание/установка пакетов%s\n' \
                    "$C_DIM" "$idle" "$C_RESET"
            else
                break  # EOF
            fi
        fi
    done
}

# Запуск пакетной команды с видимым прогрессом. Возврат = код команды (не фильтра).
_pm_run() {
    local desc="$1"; shift
    local rc=0
    log "$desc"
    set +e
    if command -v stdbuf >/dev/null 2>&1; then
        stdbuf -oL -eL "$@" 2>&1 | _pm_filter
    else
        "$@" 2>&1 | _pm_filter
    fi
    rc=${PIPESTATUS[0]}
    set -e
    return "$rc"
}

_wait_apt_lock() {
    local i=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
       || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 \
       || fuser /var/lib/dpkg/lock >/dev/null 2>&1; do
        if [[ "$i" -eq 0 ]]; then
            warn "apt занят другим процессом — жду освобождения…"
        fi
        i=$((i + 1))
        if [[ "$i" -ge 90 ]]; then
            warn "apt всё ещё занят (>3 мин) — пробую продолжить"
            break
        fi
        if [[ $((i % 5)) -eq 0 ]]; then
            printf '  %s… ждём apt lock (%ss)%s\n' "$C_DIM" "$((i * 2))" "$C_RESET"
        fi
        sleep 2
    done
}

install_os_packages() {
    local pm="unknown" rc=0

    if command -v apt-get >/dev/null 2>&1; then pm="apt"
    elif command -v dnf >/dev/null 2>&1; then pm="dnf"
    elif command -v microdnf >/dev/null 2>&1; then pm="microdnf"
    elif command -v yum >/dev/null 2>&1; then pm="yum"
    elif command -v apk >/dev/null 2>&1; then pm="apk"
    elif command -v zypper >/dev/null 2>&1; then pm="zypper"
    elif command -v pacman >/dev/null 2>&1; then pm="pacman"
    fi

    # Самая первая строка шага — сразу видно, что идёт прогресс
    log "Пакеты ОС [$pm] — установка зависимостей (прогресс ниже)…"
    printf '  %sнужны: curl, tar, python3 · желательно: rsync, ca-certificates%s\n' \
        "$C_DIM" "$C_RESET"

    case "$pm" in
        apt)
            export DEBIAN_FRONTEND=noninteractive
            export NEEDRESTART_MODE="${NEEDRESTART_MODE:-a}"
            export APT_LISTCHANGES_FRONTEND=none
            _wait_apt_lock
            rc=0
            _pm_run "Пакеты ОС (1/2): apt-get update…" apt-get update -y || rc=$?
            if [[ "$rc" -ne 0 ]]; then
                warn "apt-get update код $rc — пробуем install всё равно"
            else
                ok "apt индексы обновлены"
            fi
            _wait_apt_lock
            rc=0
            _pm_run "Пакеты ОС (2/2): install curl ca-certificates tar rsync python3 python3-venv…" \
                apt-get install -y --no-install-recommends \
                    curl ca-certificates tar rsync python3 python3-venv || rc=$?
            if [[ "$rc" -ne 0 ]]; then
                warn "полный набор не встал (код $rc) — ставлю минимум без python3-venv"
                _pm_run "Пакеты ОС: минимальный install…" \
                    apt-get install -y --no-install-recommends \
                        curl ca-certificates tar rsync python3 \
                    || die "apt-get install не удался"
            fi
            ok "Пакеты ОС готовы (apt)"
            ;;
        dnf)
            _pm_run "Пакеты ОС: dnf install…" \
                dnf install -y curl tar rsync python3 ca-certificates \
                || die "dnf install не удался"
            ok "Пакеты ОС готовы (dnf)"
            ;;
        microdnf)
            _pm_run "Пакеты ОС: microdnf install…" \
                microdnf install -y curl tar rsync python3 ca-certificates \
                || die "microdnf install не удался"
            ok "Пакеты ОС готовы (microdnf)"
            ;;
        yum)
            _pm_run "Пакеты ОС: yum install…" \
                yum install -y curl tar rsync python3 ca-certificates \
                || die "yum install не удался"
            ok "Пакеты ОС готовы (yum)"
            ;;
        apk)
            _pm_run "Пакеты ОС: apk update…" apk update || warn "apk update с ошибкой — пробую add"
            _pm_run "Пакеты ОС: apk add…" \
                apk add --no-cache curl tar rsync python3 ca-certificates \
                || die "apk add не удался"
            ok "Пакеты ОС готовы (apk)"
            ;;
        zypper)
            _pm_run "Пакеты ОС: zypper install…" \
                zypper --non-interactive install -y curl tar rsync python3 ca-certificates \
                || die "zypper install не удался"
            ok "Пакеты ОС готовы (zypper)"
            ;;
        pacman)
            _pm_run "Пакеты ОС: pacman -Sy…" \
                pacman -Sy --noconfirm --needed curl tar rsync python ca-certificates \
                || die "pacman install не удался"
            ok "Пакеты ОС готовы (pacman)"
            ;;
        *)
            warn "Неизвестный пакетный менеджер — проверяю curl/python3/tar вручную"
            warn "Поддерживаются: apt, dnf, yum, microdnf, apk, zypper, pacman"
            ;;
    esac

    command -v curl >/dev/null 2>&1 || die "Нужен curl (установите пакет curl)"
    if ! command -v python3 >/dev/null 2>&1; then
        if command -v python >/dev/null 2>&1; then
            warn "python3 не найден, есть python — создаю shim /usr/local/bin/python3"
            ln -sf "$(command -v python)" /usr/local/bin/python3 2>/dev/null || true
        fi
    fi
    command -v python3 >/dev/null 2>&1 || die "Нужен python3 (установите пакет python3)"
    if ! command -v rsync >/dev/null 2>&1; then
        warn "rsync нет — будет копирование через tar (чуть медленнее)"
    fi
    command -v tar >/dev/null 2>&1 || die "Нужен tar"
    local have="curl · python3 · tar"
    command -v rsync >/dev/null 2>&1 && have+=" · rsync"
    ok "Зависимости ОС: $have"
}

# ── .env helpers ───────────────────────────────────────────────
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
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

env_get() {
    local key="$1"
    [[ -f "${ENV_FILE:-}" ]] || { echo ""; return; }
    grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true
}

# ── Telegram getMe ─────────────────────────────────────────────
verify_bot_token() {
    local token="$1"
    local tmp
    tmp="$(mktemp)"
    if ! curl -fsSL --connect-timeout 15 --max-time 30 \
        -o "$tmp" "https://api.telegram.org/bot${token}/getMe"; then
        rm -f "$tmp"
        return 1
    fi
    if ! BOT_USERNAME="$(
        python3 - "$tmp" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if not data.get("ok"):
    raise SystemExit(1)
r = data.get("result") or {}
u = (r.get("username") or "").strip()
if not u:
    raise SystemExit(1)
print(u)
print(r.get("id") or "")
print(r.get("first_name") or "")
PY
    )"; then
        rm -f "$tmp"
        return 1
    fi
    rm -f "$tmp"
    BOT_ID="$(printf '%s\n' "$BOT_USERNAME" | sed -n '2p')"
    BOT_NAME="$(printf '%s\n' "$BOT_USERNAME" | sed -n '3p')"
    BOT_USERNAME="$(printf '%s\n' "$BOT_USERNAME" | sed -n '1p')"
    return 0
}

# ── download code ──────────────────────────────────────────────
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
    if curl -fsSL --connect-timeout 20 --max-time 60 \
        -H "Accept: application/vnd.github+json" -H "User-Agent: vpn-bot-install" \
        -o "$api" "https://api.github.com/repos/${SLUG}/releases/latest"; then
        tag="$(python3 -c "import json;d=json.load(open('$api'));print(d.get('tag_name') or '')" 2>/dev/null || true)"
        if [[ -n "$tag" ]]; then
            archive_url="https://github.com/${SLUG}/archive/refs/tags/${tag}.tar.gz"
            log "Канал: stable · $tag"
        fi
    else
        warn "GitHub API releases недоступен — fallback на ветку $BRANCH"
    fi
    rm -f "$api"
    if [[ -z "$archive_url" ]]; then
        archive_url="https://github.com/${SLUG}/archive/refs/heads/${BRANCH}.tar.gz"
        warn "Релизов нет / API fail — ставлю ветку $BRANCH"
    fi
    log "Загрузка архива (полоса прогресса curl)…"
    if ! curl -fL --connect-timeout 20 --max-time 300 --progress-bar \
        -o "$tmp/src.tar.gz" "$archive_url"; then
        rm -rf "$tmp"
        die "Не удалось скачать $archive_url"
    fi
    printf '\n'  # после progress-bar
    mkdir -p "$tmp/extract"
    tar -xzf "$tmp/src.tar.gz" -C "$tmp/extract"
    src="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
    [[ -f "$src/app.py" ]] || die "В архиве нет app.py"
    mkdir -p "$APP_DIR"
    if [[ -f "$src/deploy/lib/slim_excludes.sh" ]]; then
        # shellcheck source=/dev/null
        source "$src/deploy/lib/slim_excludes.sh"
    else
        slim_rsync_exclude_args() {
            printf '%s\n' --exclude=docs/ --exclude=report/ --exclude=scripts/dev/ \
                --exclude=.github/ --exclude='*.md' --exclude=.env --exclude=data/ \
                --exclude=.venv/ --exclude=deploy/state.env --exclude=.git/
        }
        slim_purge_docs_from_app_dir() {
            local root="${1:-}"
            [[ -d "$root" ]] || return 0
            rm -rf "$root/docs" "$root/report" "$root/scripts/dev" 2>/dev/null || true
            find "$root" -maxdepth 1 -type f -name '*.md' -delete 2>/dev/null || true
        }
    fi
    log "Раскладка файлов (slim: без docs/)…"
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
    if [[ -f "$ENV_FILE" ]]; then
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

    printf '\n%s▸ Telegram%s\n' "$C_BOLD" "$C_RESET"
    local token=""
    while true; do
        ask_secret "BOT_TOKEN (от @BotFather)"
        token="$(printf '%s' "$REPLY" | tr -d '[:space:]')"
        if [[ -z "$token" ]]; then
            warn "Токен пустой — попробуйте снова"
            continue
        fi
        log "Проверяю токен через api.telegram.org/getMe…"
        if verify_bot_token "$token"; then
            ok "Бот доступен: @${BOT_USERNAME} (id ${BOT_ID})"
            break
        fi
        warn "Токен не прошёл getMe (сеть или неверный токен) — введите снова"
    done
    env_set "BOT_TOKEN" "$token"

    local admins
    ask "BOT_ADMINS (Telegram user id, через запятую)" "$(env_get BOT_ADMINS)"
    admins="$(printf '%s' "$REPLY" | tr -d ' ')"
    [[ -n "$admins" ]] || die "BOT_ADMINS обязателен"
    env_set "BOT_ADMINS" "$admins"

    ask "BOT_BRAND (название в меню, Enter = как есть)" "$(env_get BOT_BRAND)"
    [[ -n "$REPLY" ]] && env_set "BOT_BRAND" "$REPLY"

    printf '\n%s▸ Панель 3x-ui (Primary)%s\n' "$C_BOLD" "$C_RESET"
    printf '  %sПример: https://panel.example.com/secret-path  (без /panel/ в конце)%s\n' "$C_DIM" "$C_RESET"
    ask "XUI_HOST" "$(env_get XUI_HOST)"
    local host
    host="$(printf '%s' "$REPLY" | sed 's|/*$||')"
    [[ -n "$host" ]] || die "XUI_HOST обязателен"
    case "$host" in
        http://*|https://*) ;;
        *) host="https://$host" ;;
    esac
    env_set "XUI_HOST" "$host"

    if ask_yn "Использовать API Token панели? (N = логин/пароль)" "Y"; then
        ask_secret "XUI_TOKEN (Settings → API Token)"
        [[ -n "$REPLY" ]] || die "XUI_TOKEN пустой"
        env_set "XUI_TOKEN" "$REPLY"
        env_set "XUI_USERNAME" ""
        env_set "XUI_PASSWORD" ""
    else
        ask "XUI_USERNAME" "$(env_get XUI_USERNAME)"
        [[ -n "$REPLY" ]] || die "XUI_USERNAME пустой"
        env_set "XUI_USERNAME" "$REPLY"
        ask_secret "XUI_PASSWORD"
        [[ -n "$REPLY" ]] || die "XUI_PASSWORD пустой"
        env_set "XUI_PASSWORD" "$REPLY"
        env_set "XUI_TOKEN" ""
    fi

    ask "SUBSCRIPTION_BASE_URL (Enter = пропустить)" "$(env_get SUBSCRIPTION_BASE_URL)"
    if [[ -n "$REPLY" ]]; then
        env_set "SUBSCRIPTION_BASE_URL" "$(printf '%s' "$REPLY" | sed 's|/*$||')/"
    fi

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
}

# ── main ───────────────────────────────────────────────────────
main() {
    [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Запустите от root: curl … | sudo bash"
    ensure_tty
    banner "install · мастер одной команды"

    install_os_packages

    log "Каталог установки: $APP_DIR"
    fetch_code
    run_wizard

    printf '\n'
    log "Запускаю полную установку (Redis, venv, systemd)…"
    export APP_DIR
    if ! bash "$APP_DIR/deploy/vpn-bot-ctl.sh" install; then
        warn "ctl install завершился с ошибкой — проверьте .env и journalctl"
        warn "Повтор: sudo bash $APP_DIR/deploy/vpn-bot-ctl.sh  → пункт 1"
        warn "Или: sudo vpnplategabot  (если ярлык уже появился)"
        exit 1
    fi

    printf '\n'
    ok "Установка завершена"
    ENV_FILE="${ENV_FILE:-$APP_DIR/.env}"
    local wh test_mode
    wh="$(env_get PUBLIC_WEBHOOK_URL | tr -d '[:space:]')"
    test_mode="$(env_get TEST_MODE | tr -d '[:space:]')"

    printf '\n%sДальше:%s\n' "$C_BOLD" "$C_RESET"
    printf '  • Меню:     %svpnplategabot%s  (или sudo bash %s/deploy/vpn-bot-ctl.sh)\n' "$C_GREEN" "$C_RESET" "$APP_DIR"
    printf '  • Обновление: пункт 2 (stable) или 3 (edge)\n'
    printf '  • Health:   %scurl -s http://127.0.0.1:8080/health%s\n' "$C_DIM" "$C_RESET"
    if [[ -n "${BOT_USERNAME:-}" ]]; then
        printf '  • Бот:      %shttps://t.me/%s%s\n' "$C_CYAN" "$BOT_USERNAME" "$C_RESET"
    fi

    printf '\n%sWebhook (Platega):%s\n' "$C_BOLD" "$C_RESET"
    if [[ "$test_mode" == "true" ]]; then
        printf '  • %sСейчас TEST_MODE=true%s — оплаты симулируются, боевой webhook не обязателен.\n' \
            "$C_YELLOW" "$C_RESET"
        printf '  • Для прода: задайте Platega в .env, %sTEST_MODE=false%s и %sPUBLIC_WEBHOOK_URL%s\n' \
            "$C_BOLD" "$C_RESET" "$C_BOLD" "$C_RESET"
        printf '    (обычно %shttps://ваш-домен/platega-webhook%s).\n' "$C_DIM" "$C_RESET"
        printf '  • Этот URL нужно:\n'
        printf '      1) вписать в %sличном кабинете Platega%s (Callback / Webhook URL);\n' \
            "$C_YELLOW$C_BOLD" "$C_RESET"
        printf '      2) %sдобавить в nginx%s: location → proxy_pass http://127.0.0.1:8080;\n' \
            "$C_YELLOW$C_BOLD" "$C_RESET"
    else
        if [[ -n "$wh" ]]; then
            printf '  • URL из .env:  %s%s%s\n' "$C_CYAN$C_BOLD" "$wh" "$C_RESET"
        else
            printf '  • %sPUBLIC_WEBHOOK_URL пуст%s — задайте HTTPS URL в .env\n' \
                "$C_YELLOW" "$C_RESET"
            wh="https://ваш-домен/platega-webhook"
            printf '  • Пример:      %s%s%s\n' "$C_DIM" "$wh" "$C_RESET"
        fi
        printf '  • Этот адрес нужен в %sличном кабинете Platega%s (Callback / Webhook URL) —\n' \
            "$C_YELLOW$C_BOLD" "$C_RESET"
        printf '    без него Platega не сможет подтверждать оплаты боту.\n'
        printf '  • %sДобавьте его в nginx%s (HTTPS-сайт) и проксируйте на бота:\n' \
            "$C_YELLOW$C_BOLD" "$C_RESET"
        printf '      location /platega-webhook {\n'
        printf '          proxy_pass http://127.0.0.1:8080;\n'
        printf '          proxy_set_header Host $host;\n'
        printf '          proxy_set_header X-Real-IP $remote_addr;\n'
        printf '      }\n'
        printf '  • Проверка снаружи: %scurl -sI %s%s\n' "$C_DIM" "${wh:-https://домен/platega-webhook}" "$C_RESET"
    fi
    printf '\n'
}

main "$@"

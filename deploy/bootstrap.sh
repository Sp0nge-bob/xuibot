#!/usr/bin/env bash
# Однострочная установка / починка ctl без локального git:
#
#   curl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/bootstrap.sh \
#     | sudo bash -s -- /opt/vpn-bot
#
# Сохраняет .env и data/. Дальше: sudo bash /opt/vpn-bot/deploy/vpn-bot-ctl.sh

set -euo pipefail

APP_DIR="${1:-/opt/vpn-bot}"
REMOTE="${GIT_REMOTE:-https://github.com/Sp0nge-bob/xuibot.git}"
BRANCH="${GIT_BRANCH:-main}"
SLUG="Sp0nge-bob/xuibot"

if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
    C_RESET=$'\033[0m' C_BOLD=$'\033[1m' C_DIM=$'\033[2m'
    C_CYAN=$'\033[36m' C_GREEN=$'\033[32m' C_YELLOW=$'\033[33m' C_RED=$'\033[31m'
else
    C_RESET="" C_BOLD="" C_DIM="" C_CYAN="" C_GREEN="" C_YELLOW="" C_RED=""
fi

# UTF-8 frames when locale allows; else ASCII (no mojibake)
case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
    *UTF-8*|*utf8*|*UTF8*)
        _TL='╭' _TR='╮' _BL='╰' _BR='╯' _H='─' _V='│' ;;
    *)
        if locale charmap 2>/dev/null | grep -qi 'utf-8'; then
            _TL='╭' _TR='╮' _BL='╰' _BR='╯' _H='─' _V='│'
        else
            _TL='+' _TR='+' _BL='+' _BR='+' _H='-' _V='|'
        fi
        ;;
esac

_bs_log()  { printf '%s==>%s %s\n' "$C_CYAN" "$C_RESET" "$*"; }
_bs_ok()   { printf '%sOK%s  %s\n' "$C_GREEN" "$C_RESET" "$*"; }
_bs_err()  { printf '%sERR%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; }

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    _bs_err "Запустите от root: curl … | sudo bash -s -- $APP_DIR"
    exit 1
fi

printf '\n%s%s' "$C_CYAN" "$_TL"
printf '%s' "$_H$_H"
printf '%s VPN Bot %s' "$C_RESET$C_BOLD" "$C_RESET$C_CYAN"
i=0; while [[ $i -lt 28 ]]; do printf '%s' "$_H"; i=$((i + 1)); done
printf '%s%s\n' "$_TR" "$C_RESET"
printf '%s%s%s  %sbootstrap · без git%s' "$C_CYAN" "$_V" "$C_RESET" "$C_DIM" "$C_RESET"
pad=24; while [[ $pad -gt 0 ]]; do printf ' '; pad=$((pad - 1)); done
printf '%s%s%s\n' "$C_CYAN" "$_V" "$C_RESET"
printf '%s%s' "$C_CYAN" "$_BL"
i=0; while [[ $i -lt 44 ]]; do printf '%s' "$_H"; i=$((i + 1)); done
printf '%s%s\n\n' "$_BR" "$C_RESET"

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    _bs_log "Пакеты: curl tar rsync python3…"
    apt-get update -qq
    apt-get install -y curl ca-certificates tar rsync python3 >/dev/null
fi

command -v curl >/dev/null || { _bs_err "нужен curl"; exit 1; }
command -v python3 >/dev/null || { _bs_err "нужен python3"; exit 1; }

slug_from_remote() {
    local r="$1"
    r="${r%.git}"; r="${r%/}"
    if [[ "$r" =~ github\.com[:/]+([^/]+)/([^/]+)$ ]]; then
        echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        return
    fi
    echo "$SLUG"
}

SLUG="$(slug_from_remote "$REMOTE")"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

_bs_log "Каталог: $APP_DIR"
_bs_log "Репозиторий: $SLUG"

# Prefer latest release tarball; fallback to branch archive
ARCHIVE_URL=""
TAG=""
API="$(mktemp)"
if curl -fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: vpn-bot-bootstrap" \
    -o "$API" "https://api.github.com/repos/${SLUG}/releases/latest"; then
    TAG="$(python3 -c "import json;d=json.load(open('$API'));print(d.get('tag_name') or '')" 2>/dev/null || true)"
    if [[ -n "$TAG" ]]; then
        ARCHIVE_URL="https://github.com/${SLUG}/archive/refs/tags/${TAG}.tar.gz"
        _bs_log "Канал: stable · $TAG"
    fi
fi
rm -f "$API"

if [[ -z "$ARCHIVE_URL" ]]; then
    ARCHIVE_URL="https://github.com/${SLUG}/archive/refs/heads/${BRANCH}.tar.gz"
    _bs_log "Канал: edge · ветка $BRANCH (релизов нет)"
fi

_bs_log "Скачивание архива…"
curl -fsSL -o "$TMP/src.tar.gz" "$ARCHIVE_URL"
mkdir -p "$TMP/extract"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/extract"
SRC="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -f "$SRC/app.py" ]] || { _bs_err "в архиве нет app.py"; exit 1; }

mkdir -p "$APP_DIR"
_bs_log "Раскладка кода (сохраняем .env · data · .venv)…"
if command -v rsync >/dev/null 2>&1; then
    rsync -a \
        --exclude '.env' \
        --exclude '.env.local' \
        --exclude 'data/' \
        --exclude '.venv/' \
        --exclude 'deploy/state.env' \
        --exclude '.git/' \
        "$SRC"/ "$APP_DIR"/
else
    (cd "$SRC" && tar -cf - --exclude='./.env' --exclude='./data' --exclude='./.venv' --exclude='./.git' . \
        | tar -xf - -C "$APP_DIR")
fi

chmod +x "$APP_DIR/deploy/vpn-bot-ctl.sh" "$APP_DIR/deploy/"*.sh 2>/dev/null || true
chmod +x "$APP_DIR/deploy/lib/"*.sh 2>/dev/null || true

echo
_bs_ok "Код в $APP_DIR"
printf '\n%sДальше:%s\n' "$C_BOLD" "$C_RESET"
printf '  %sПолная установка одной командой (мастер .env + systemd):%s\n' "$C_BOLD" "$C_RESET"
printf '    %scurl -fsSL https://raw.githubusercontent.com/Sp0nge-bob/xuibot/main/deploy/install.sh \\%s\n' "$C_GREEN" "$C_RESET"
printf '      %s| sudo bash -s -- %s%s\n\n' "$C_GREEN" "$APP_DIR" "$C_RESET"
printf '  Или вручную:\n'
printf '  %s1.%s  Проверьте %s/.env%s\n' "$C_CYAN" "$C_RESET" "$APP_DIR" "$C_DIM (из .env.example)$C_RESET"
printf '  %s2.%s  %ssudo bash %s/deploy/vpn-bot-ctl.sh%s → пункт 1\n\n' "$C_CYAN" "$C_RESET" "$C_GREEN" "$APP_DIR" "$C_RESET"

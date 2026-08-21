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

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    echo "!! Запустите от root: curl … | sudo bash -s -- $APP_DIR" >&2
    exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y curl ca-certificates tar rsync python3 >/dev/null
fi

command -v curl >/dev/null || { echo "!! нужен curl"; exit 1; }
command -v python3 >/dev/null || { echo "!! нужен python3"; exit 1; }

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

echo "==> Bootstrap → $APP_DIR (repo $SLUG)"

# Prefer latest release tarball; fallback to branch archive
ARCHIVE_URL=""
TAG=""
API="$(mktemp)"
if curl -fsSL -H "Accept: application/vnd.github+json" -H "User-Agent: vpn-bot-bootstrap" \
    -o "$API" "https://api.github.com/repos/${SLUG}/releases/latest"; then
    TAG="$(python3 -c "import json;d=json.load(open('$API'));print(d.get('tag_name') or '')" 2>/dev/null || true)"
    if [[ -n "$TAG" ]]; then
        ARCHIVE_URL="https://github.com/${SLUG}/archive/refs/tags/${TAG}.tar.gz"
        echo "==> Latest release: $TAG"
    fi
fi
rm -f "$API"

if [[ -z "$ARCHIVE_URL" ]]; then
    ARCHIVE_URL="https://github.com/${SLUG}/archive/refs/heads/${BRANCH}.tar.gz"
    echo "==> Нет релизов — качаем ветку $BRANCH"
fi

curl -fsSL -o "$TMP/src.tar.gz" "$ARCHIVE_URL"
mkdir -p "$TMP/extract"
tar -xzf "$TMP/src.tar.gz" -C "$TMP/extract"
SRC="$(find "$TMP/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -f "$SRC/app.py" ]] || { echo "!! в архиве нет app.py"; exit 1; }

mkdir -p "$APP_DIR"
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

echo "✓ Код разложен в $APP_DIR"
echo "==> Дальше:"
echo "    1) Проверьте $APP_DIR/.env (скопируйте из .env.example при первом запуске)"
echo "    2) sudo bash $APP_DIR/deploy/vpn-bot-ctl.sh"
echo "       → пункт 1 (установка), затем 2 (релиз) по необходимости"

#!/usr/bin/env bash
# Подготовка и публикация GitHub Release (мейнтейнер).
#
#   ./scripts/cut_release.sh           # читает VERSION → tag vX.Y.Z
#   ./scripts/cut_release.sh 1.0.1     # явная версия
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VER="${1:-}"
if [[ -z "$VER" ]]; then
    [[ -f VERSION ]] || { echo "Нет VERSION"; exit 1; }
    VER="$(tr -d '[:space:]' <VERSION)"
fi
VER="${VER#v}"
TAG="v${VER}"

if [[ -n "$(git status --porcelain)" ]]; then
    echo "!! Есть незакоммиченные изменения — закоммитьте сначала"
    exit 1
fi

echo "==> Release $TAG"
echo "    1) Убедитесь, что VERSION и pyproject.toml = $VER"
echo "    2) git tag -a $TAG -m \"Release $TAG\""
echo "    3) git push origin main && git push origin $TAG"
echo "    4) gh release create $TAG --title \"VPN Shop Bot $TAG\" --notes-file docs/RELEASE_v${VER}.md"
echo
read -r -p "Выполнить tag + push + gh release сейчас? [y/N] " ok
[[ "$ok" =~ ^[yY]$ ]] || { echo "Отменено (команды выше можно вручную)"; exit 0; }

git tag -a "$TAG" -m "Release $TAG" 2>/dev/null || git tag -f -a "$TAG" -m "Release $TAG"
git push origin HEAD
git push origin "$TAG"
NOTES="docs/RELEASE_v${VER}.md"
if [[ ! -f "$NOTES" ]]; then
    NOTES="$(mktemp)"
    echo "VPN Shop Bot $TAG" >"$NOTES"
fi
gh release create "$TAG" --title "VPN Shop Bot $TAG" --notes-file "$NOTES" || \
    gh release edit "$TAG" --title "VPN Shop Bot $TAG" --notes-file "$NOTES"
echo "✓ https://github.com/Sp0nge-bob/xuibot/releases/tag/$TAG"

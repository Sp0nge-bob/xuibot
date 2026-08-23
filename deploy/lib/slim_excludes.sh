# shellcheck shell=bash
# Что не копируем на VPS при install/update (на GitHub остаётся полностью).
#
# Не использовать rsync --delete-excluded вместе с exclude .env —
# иначе сотрётся .env на сервере.

# Аргументы rsync --exclude=...
slim_rsync_exclude_args() {
    printf '%s\n' \
        --exclude=docs/ \
        --exclude=report/ \
        --exclude=scripts/dev/ \
        --exclude=.github/ \
        --exclude='*.md' \
        --exclude=.env \
        --exclude=.env.local \
        --exclude=.env.production \
        --exclude=data/ \
        --exclude=.venv/ \
        --exclude=deploy/state.env \
        --exclude=.git/ \
        --exclude=.deploy_revision \
        --exclude=.deploy_meta \
        --exclude='__pycache__/' \
        --exclude='*.pyc' \
        --exclude=vpn_platega_bot.egg-info/ \
        --exclude=.pytest_cache/ \
        --exclude=.mypy_cache/ \
        --exclude=.ruff_cache/
}

# Убрать уже лежавший на сервере «мусор» после обновления с полного архива
slim_purge_docs_from_app_dir() {
    local root="${1:-${APP_DIR:-}}"
    [[ -n "$root" && -d "$root" ]] || return 0
    rm -rf "$root/docs" "$root/report" "$root/scripts/dev" "$root/.github" \
        "$root/vpn_platega_bot.egg-info" 2>/dev/null || true
    # только корень репозитория
    find "$root" -maxdepth 1 -type f -name '*.md' -delete 2>/dev/null || true
}

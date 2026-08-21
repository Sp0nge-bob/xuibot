# shellcheck shell=bash
# Идемпотентная установка / обновление (пункт 1 меню) + обновление кода (релиз / коммит)

DEFAULT_GIT_REMOTE="${DEFAULT_GIT_REMOTE:-https://github.com/Sp0nge-bob/xuibot.git}"
DEFAULT_GIT_BRANCH="${DEFAULT_GIT_BRANCH:-main}"
DEPLOY_REVISION_FILE=".deploy_revision"
DEPLOY_META_FILE=".deploy_meta"

# ── remote / slug ──────────────────────────────────────────────

resolve_git_remote() {
    if [[ -n "${GIT_REMOTE:-}" ]]; then
        echo "$GIT_REMOTE"
        return
    fi
    if [[ -f "$STATE_FILE" ]]; then
        local _gr=""
        _gr="$(grep -E '^GIT_REMOTE=' "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
        if [[ -n "$_gr" ]]; then
            echo "$_gr"
            return
        fi
    fi
    if [[ -d "$APP_DIR/.git" ]]; then
        local url=""
        url="$(git -C "$APP_DIR" remote get-url origin 2>/dev/null || true)"
        if [[ -n "$url" ]]; then
            echo "$url"
            return
        fi
    fi
    echo "$DEFAULT_GIT_REMOTE"
}

resolve_git_branch() {
    if [[ -n "${GIT_BRANCH:-}" ]]; then
        echo "$GIT_BRANCH"
        return
    fi
    if [[ -f "$STATE_FILE" ]]; then
        local _gb=""
        _gb="$(grep -E '^GIT_BRANCH=' "$STATE_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
        if [[ -n "$_gb" ]]; then
            echo "$_gb"
            return
        fi
    fi
    echo "$DEFAULT_GIT_BRANCH"
}

save_git_remote_to_state() {
    local remote="$1"
    [[ -n "$remote" ]] || return 0
    mkdir -p "$DEPLOY_DIR"
    if [[ -f "$STATE_FILE" ]] && grep -qE '^GIT_REMOTE=' "$STATE_FILE" 2>/dev/null; then
        sed -i "s|^GIT_REMOTE=.*|GIT_REMOTE=$remote|" "$STATE_FILE" 2>/dev/null || true
    elif [[ -f "$STATE_FILE" ]]; then
        printf '\nGIT_REMOTE=%s\n' "$remote" >>"$STATE_FILE"
    fi
}

github_slug_from_remote() {
    local remote="$1"
    remote="${remote%.git}"
    remote="${remote%/}"
    if [[ "$remote" =~ github\.com[:/]+([^/]+)/([^/]+)$ ]]; then
        echo "${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        return 0
    fi
    if [[ "$remote" =~ ^([^/]+)/([^/]+)$ ]]; then
        echo "$remote"
        return 0
    fi
    return 1
}

# ── HTTP / JSON helpers ────────────────────────────────────────

_http_get() {
    local url="$1" out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 20 --max-time 180 \
            -H "Accept: application/vnd.github+json" \
            -H "User-Agent: vpn-platega-bot-ctl" \
            -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$out" --header="Accept: application/vnd.github+json" "$url"
    else
        die "Нужен curl или wget для скачивания обновления"
    fi
}

_json_get() {
    # usage: _json_get file.py key → prints value via python
    local file="$1"
    shift
    python3 - "$file" "$@" <<'PY'
import json, sys
path = sys.argv[1]
keys = sys.argv[2:]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
cur = data
for k in keys:
    if isinstance(cur, dict):
        cur = cur.get(k)
    else:
        cur = None
        break
if cur is None:
    sys.exit(1)
print(cur)
PY
}

# ── deploy meta ────────────────────────────────────────────────

read_deploy_meta_field() {
    local key="$1" file="$APP_DIR/$DEPLOY_META_FILE"
    [[ -f "$file" ]] || return 1
    grep -E "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2-
}

write_deploy_meta() {
    local channel="$1" version="$2" sha="$3" remote="$4"
    local now
    now="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    cat >"$APP_DIR/$DEPLOY_META_FILE" <<EOF
CHANNEL=$channel
VERSION=$version
SHA=$sha
REMOTE=$remote
UPDATED_AT=$now
EOF
    printf '%s\n' "$sha" >"$APP_DIR/$DEPLOY_REVISION_FILE"
    save_git_remote_to_state "$remote"
}

format_installed_version() {
    local channel version sha short
    if [[ -f "$APP_DIR/$DEPLOY_META_FILE" ]]; then
        channel="$(read_deploy_meta_field CHANNEL || true)"
        version="$(read_deploy_meta_field VERSION || true)"
        sha="$(read_deploy_meta_field SHA || true)"
        if [[ -n "$version" ]]; then
            if [[ "$channel" == "release" ]]; then
                echo "$version (stable)"
            else
                echo "${version} (edge)"
            fi
            return
        fi
    fi
    if [[ -f "$APP_DIR/$DEPLOY_REVISION_FILE" ]]; then
        sha="$(tr -d '[:space:]' <"$APP_DIR/$DEPLOY_REVISION_FILE")"
        short="${sha:0:7}"
        echo "${short:-?} (commit)"
        return
    fi
    if [[ -f "$APP_DIR/VERSION" ]]; then
        echo "$(tr -d '[:space:]' <"$APP_DIR/VERSION") (файловая)"
        return
    fi
    echo "неизвестно"
}

# ── overlay archive onto APP_DIR ───────────────────────────────

apply_code_tarball() {
    # args: archive_url channel version sha remote
    local archive_url="$1" channel="$2" version="$3" sha="$4" remote="$5"
    local short current_sha tmp tarball extract_root
    short="${sha:0:7}"

    current_sha="$(read_deploy_meta_field SHA 2>/dev/null || true)"
    if [[ -z "$current_sha" && -f "$APP_DIR/$DEPLOY_REVISION_FILE" ]]; then
        current_sha="$(tr -d '[:space:]' <"$APP_DIR/$DEPLOY_REVISION_FILE" || true)"
    fi
    if [[ -n "$current_sha" && "$current_sha" == "$sha" ]]; then
        ok "Код уже актуален: $version ($short)"
        write_deploy_meta "$channel" "$version" "$sha" "$remote"
        return 0
    fi

    tmp="$(mktemp -d)"
    tarball="$tmp/src.tar.gz"
    log "Скачиваем $archive_url"
    if ! _http_get "$archive_url" "$tarball"; then
        rm -rf "$tmp"
        warn "Скачивание архива не удалось"
        return 1
    fi

    mkdir -p "$tmp/extract"
    if ! tar -xzf "$tarball" -C "$tmp/extract"; then
        rm -rf "$tmp"
        warn "Не удалось распаковать архив"
        return 1
    fi
    extract_root="$(find "$tmp/extract" -mindepth 1 -maxdepth 1 -type d | head -1)"
    if [[ -z "$extract_root" || ! -f "$extract_root/app.py" ]]; then
        rm -rf "$tmp"
        warn "В архиве нет app.py — неожиданный формат"
        return 1
    fi

    log "Накладываем код на $APP_DIR (сохраняем .env, data/, .venv/)"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a \
            --delete \
            --exclude '.env' \
            --exclude '.env.local' \
            --exclude '.env.production' \
            --exclude 'data/' \
            --exclude '.venv/' \
            --exclude 'deploy/state.env' \
            --exclude '.git/' \
            --exclude "$DEPLOY_REVISION_FILE" \
            --exclude "$DEPLOY_META_FILE" \
            "$extract_root"/ "$APP_DIR"/
    else
        warn "rsync не найден — копируем через tar (без удаления устаревших файлов)"
        (
            cd "$extract_root" || exit 1
            tar -cf - \
                --exclude='./.env' \
                --exclude='./data' \
                --exclude='./.venv' \
                --exclude='./.git' \
                --exclude="./deploy/state.env" \
                . | tar -xf - -C "$APP_DIR"
        ) || {
            rm -rf "$tmp"
            return 1
        }
    fi

    write_deploy_meta "$channel" "$version" "$sha" "$remote"
    rm -rf "$tmp"
    if [[ -n "$current_sha" ]]; then
        ok "Код обновлён: ${current_sha:0:7} → $short ($version, $channel)"
    else
        ok "Код установлен: $version ($short, $channel)"
    fi
    return 0
}

github_branch_sha() {
    local slug="$1" branch="$2"
    local api_url tmp sha
    api_url="https://api.github.com/repos/${slug}/commits/${branch}"
    tmp="$(mktemp)"
    if ! _http_get "$api_url" "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    sha="$(_json_get "$tmp" sha 2>/dev/null || true)"
    rm -f "$tmp"
    sha="${sha:0:40}"
    [[ -n "$sha" && ${#sha} -ge 7 ]] || return 1
    echo "$sha"
}

# ── public update modes ────────────────────────────────────────

update_from_latest_release() {
    local remote slug tmp tag tarball_url sha api_url
    remote="$(resolve_git_remote)"
    if ! slug="$(github_slug_from_remote "$remote")"; then
        warn "Не разобрать GitHub remote: $remote"
        return 1
    fi

    log "Канал: stable (последний GitHub Release)"
    log "Репозиторий: $slug"
    api_url="https://api.github.com/repos/${slug}/releases/latest"
    tmp="$(mktemp)"
    if ! _http_get "$api_url" "$tmp"; then
        rm -f "$tmp"
        warn "Не удалось получить latest release (сеть / нет релизов / приватный репо)."
        warn "Используйте пункт 3 — обновление до последнего коммита (edge)."
        return 1
    fi
    # GitHub returns {"message":"Not Found"} when no releases
    if grep -q '"Not Found"' "$tmp" 2>/dev/null || grep -q '"message": "Not Found"' "$tmp" 2>/dev/null; then
        rm -f "$tmp"
        warn "В репозитории ещё нет GitHub Releases."
        warn "Прод-обновление: дождитесь релиза или пункт 3 (последний коммит)."
        return 1
    fi

    tag="$(_json_get "$tmp" tag_name 2>/dev/null || true)"
    tarball_url="$(_json_get "$tmp" tarball_url 2>/dev/null || true)"
    # target_commitish may be branch name; prefer uploading assetless tag archive + resolve sha
    rm -f "$tmp"

    if [[ -z "$tag" ]]; then
        warn "В ответе API нет tag_name — релизов нет или формат изменился."
        warn "Используйте пункт 3 (edge / последний коммит)."
        return 1
    fi

    if [[ -z "$tarball_url" ]]; then
        tarball_url="https://github.com/${slug}/archive/refs/tags/${tag}.tar.gz"
    fi

    # Resolve tag → commit SHA
    tmp="$(mktemp)"
    if _http_get "https://api.github.com/repos/${slug}/git/refs/tags/${tag}" "$tmp" 2>/dev/null; then
        sha="$(_json_get "$tmp" object sha 2>/dev/null || true)"
        # annotated tags: object.type=tag → need another hop; try commit sha from object
        local otype
        otype="$(python3 -c "import json; d=json.load(open('$tmp')); print(d.get('object',{}).get('type',''))" 2>/dev/null || true)"
        if [[ "$otype" == "tag" && -n "$sha" ]]; then
            local tmp2
            tmp2="$(mktemp)"
            if _http_get "https://api.github.com/repos/${slug}/git/tags/${sha}" "$tmp2" 2>/dev/null; then
                sha="$(_json_get "$tmp2" object sha 2>/dev/null || true)"
            fi
            rm -f "$tmp2"
        fi
    fi
    rm -f "$tmp"
    if [[ -z "$sha" || ${#sha} -lt 7 ]]; then
        # fallback: use tag archive URL; sha unknown — store tag as version, sha=tag
        sha="$tag"
    fi

    # Prefer codeload archive by tag (stable URL)
    local archive_url="https://github.com/${slug}/archive/refs/tags/${tag}.tar.gz"
    apply_code_tarball "$archive_url" "release" "$tag" "$sha" "$remote"
}

update_from_latest_commit() {
    local remote branch slug sha short archive_url
    remote="$(resolve_git_remote)"
    branch="$(resolve_git_branch)"
    if ! slug="$(github_slug_from_remote "$remote")"; then
        warn "Не разобрать GitHub remote: $remote"
        return 1
    fi

    log "Канал: edge (последний коммит $branch)"
    log "Репозиторий: $slug"
    if ! sha="$(github_branch_sha "$slug" "$branch")"; then
        warn "Не удалось получить SHA с api.github.com"
        return 1
    fi
    short="${sha:0:7}"
    archive_url="https://github.com/${slug}/archive/${sha}.tar.gz"
    apply_code_tarball "$archive_url" "commit" "$short" "$sha" "$remote"
}

# UPDATE_CHANNEL=release|edge  (default release for `update`)
update_bot_code() {
    local channel="${UPDATE_CHANNEL:-release}"
    case "$channel" in
        release|stable)
            update_from_latest_release
            ;;
        edge|commit|main|dev)
            update_from_latest_commit
            ;;
        *)
            die "Неизвестный UPDATE_CHANNEL=$channel (release|edge)"
            ;;
    esac
}

_cmd_update_finish() {
    if ! python_deps_ok; then
        warn "Зависимости Python устарели после обновления — ставим заново"
        ensure_venv
        ensure_python_deps || warn "pip install не удался — выполните пункт 1"
    fi
    fix_permissions
    restart_services
}

cmd_update_bot_release() {
    require_root
    load_config
    log "Обновление до последнего релиза (stable)"
    log "Каталог: $APP_DIR"
    if ! unit_is_installed "$TELEGRAM_UNIT" || ! unit_is_installed "$WEB_UNIT"; then
        warn "Службы не установлены — сначала пункт 1"
        return 1
    fi
    UPDATE_CHANNEL=release update_bot_code || return 1
    _cmd_update_finish
}

cmd_update_bot_edge() {
    require_root
    load_config
    log "Обновление до последнего коммита (edge)"
    log "Каталог: $APP_DIR"
    if ! unit_is_installed "$TELEGRAM_UNIT" || ! unit_is_installed "$WEB_UNIT"; then
        warn "Службы не установлены — сначала пункт 1"
        return 1
    fi
    UPDATE_CHANNEL=edge update_bot_code || return 1
    _cmd_update_finish
}

# backward-compatible: default = release
cmd_update_bot() {
    cmd_update_bot_release
}

cmd_reconcile() {
    require_root
    load_config
    log "Каталог: $APP_DIR"
    log "Пользователь: $SERVICE_USER"

    fix_repo_ownership_for_git
    validate_project
    ensure_env_file
    fix_env_for_systemd
    ensure_redis_server || warn "Redis не готов — без REDIS_URL FSM останется в RAM"
    ensure_redis_url_in_env
    ensure_service_user
    ensure_venv
    ensure_python_deps
    fix_permissions

    if ! verify_service_user_access; then
        ensure_python_deps_as_service_user || die "loguru/aiogram не импортируются от $SERVICE_USER"
        verify_service_user_access || die "Проверка доступа $SERVICE_USER не прошла"
    fi

    if ! start_services; then
        warn "Сервисы не запустились — см. journalctl выше"
        show_status
        return 1
    fi

    save_state
    echo
    ok "Установка / обновление завершено"
    log "Проверка: curl -s http://127.0.0.1:8080/health"
    show_status
    return 0
}

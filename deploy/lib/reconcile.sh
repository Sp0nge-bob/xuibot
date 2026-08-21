# shellcheck shell=bash
# Идемпотентная установка / обновление (пункт 1 меню)

# Upstream для обновления кода (форки: GIT_REMOTE=… или deploy/state.env)
DEFAULT_GIT_REMOTE="${DEFAULT_GIT_REMOTE:-https://github.com/Sp0nge-bob/xuibot.git}"
DEFAULT_GIT_BRANCH="${DEFAULT_GIT_BRANCH:-main}"
# Файл с SHA последнего применённого архива (без .git)
DEPLOY_REVISION_FILE=".deploy_revision"

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

# https://github.com/Owner/Repo.git → Owner/Repo
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

_http_get() {
    local url="$1" out="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --connect-timeout 20 --max-time 180 -o "$out" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$out" "$url"
    else
        die "Нужен curl или wget для скачивания обновления"
    fi
}

# SHA последнего коммита ветки через GitHub API (без локального git)
github_branch_sha() {
    local slug="$1" branch="$2"
    local api_url tmp sha
    api_url="https://api.github.com/repos/${slug}/commits/${branch}"
    tmp="$(mktemp)"
    if ! _http_get "$api_url" "$tmp"; then
        rm -f "$tmp"
        return 1
    fi
    sha="$(
        python3 - "$tmp" <<'PY' 2>/dev/null
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
print((data.get("sha") or "")[:40])
PY
    )"
    rm -f "$tmp"
    [[ -n "$sha" && ${#sha} -ge 7 ]] || return 1
    echo "$sha"
}

git_discard_deploy_script_drift() {
    # install_restart_sudoers делает chmod 755 — иначе git pull падает на «local changes»
    local rel
    for rel in deploy/restart-services.sh deploy/vpn-bot-ctl.sh; do
        [[ -f "$APP_DIR/$rel" ]] || continue
        if git -C "$APP_DIR" diff --quiet -- "$rel" 2>/dev/null; then
            continue
        fi
        warn "Сбрасываем локальные изменения $rel (обычно chmod от установки)"
        git -C "$APP_DIR" restore --source=HEAD --staged --worktree -- "$rel" 2>/dev/null \
            || git -C "$APP_DIR" checkout -- "$rel" 2>/dev/null \
            || true
    done
}

# Обновление кода из tarball GitHub (последний коммит ветки) — .git не нужен.
# Сохраняет: .env, data/, .venv/, deploy/state.env, .deploy_revision (перезапишется).
update_from_github_archive() {
    local remote branch slug sha short current archive_url tmp tarball extract_root
    remote="$(resolve_git_remote)"
    branch="$(resolve_git_branch)"

    if ! slug="$(github_slug_from_remote "$remote")"; then
        warn "Не удалось разобрать GitHub remote: $remote"
        warn "Задайте GIT_REMOTE=https://github.com/OWNER/REPO.git"
        return 1
    fi

    log "Обновление из GitHub (архив, без локального .git)"
    log "Репозиторий: $slug  ветка: $branch"

    if ! sha="$(github_branch_sha "$slug" "$branch")"; then
        warn "Не удалось получить SHA с api.github.com (сеть / лимит / приватный репо)"
        return 1
    fi
    short="${sha:0:7}"
    current=""
    [[ -f "$APP_DIR/$DEPLOY_REVISION_FILE" ]] && current="$(tr -d '[:space:]' <"$APP_DIR/$DEPLOY_REVISION_FILE" || true)"

    if [[ -n "$current" && "$current" == "$sha" ]]; then
        ok "Код уже актуален ($short)"
        save_git_remote_to_state "$remote"
        return 0
    fi

    archive_url="https://github.com/${slug}/archive/${sha}.tar.gz"
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
            "$extract_root"/ "$APP_DIR"/
    else
        warn "rsync не найден — копируем через tar (без удаления устаревших файлов)"
        # shellcheck disable=SC2164
        (
            cd "$extract_root"
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

    printf '%s\n' "$sha" >"$APP_DIR/$DEPLOY_REVISION_FILE"
    save_git_remote_to_state "$remote"
    rm -rf "$tmp"
    if [[ -n "$current" ]]; then
        ok "Код обновлён: ${current:0:7} → $short (архив GitHub)"
    else
        ok "Код установлен: $short (архив GitHub)"
    fi
    return 0
}

git_pull_repo() {
    fix_repo_ownership_for_git
    git_discard_deploy_script_drift
    log "git pull в $APP_DIR"
    local before after
    before="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if ! git -C "$APP_DIR" pull --ff-only; then
        warn "git pull не удался — проверьте сеть, доступ к origin и локальные изменения"
        warn "Подсказка: git -C $APP_DIR status ; git -C $APP_DIR remote -v"
        warn "Запасной путь: UPDATE_METHOD=archive sudo bash deploy/vpn-bot-ctl.sh update"
        return 1
    fi
    after="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if [[ "$before" == "$after" ]]; then
        ok "Код уже актуален ($after)"
    else
        ok "Код обновлён: $before → $after"
    fi
    # зафиксировать SHA и для гибридных установок
    git -C "$APP_DIR" rev-parse HEAD >"$APP_DIR/$DEPLOY_REVISION_FILE" 2>/dev/null || true
    return 0
}

# Выбор способа обновления кода:
# - UPDATE_METHOD=archive → всегда архив GitHub
# - UPDATE_METHOD=git → только git pull (нужен .git)
# - auto (по умолчанию): есть .git → pull, иначе → архив
update_bot_code() {
    local method="${UPDATE_METHOD:-auto}"
    case "$method" in
        archive|tar|github)
            update_from_github_archive
            ;;
        git|pull)
            [[ -d "$APP_DIR/.git" ]] || die "UPDATE_METHOD=git, но нет $APP_DIR/.git"
            git_pull_repo
            ;;
        auto|"")
            if [[ -d "$APP_DIR/.git" ]]; then
                git_pull_repo || {
                    warn "git pull не удался — пробуем архив с GitHub"
                    update_from_github_archive
                }
            else
                update_from_github_archive
            fi
            ;;
        *)
            die "Неизвестный UPDATE_METHOD=$method (auto|git|archive)"
            ;;
    esac
}

cmd_update_bot() {
    require_root
    load_config
    log "Обновление бота: код (git или архив GitHub) + перезапуск служб"
    log "Каталог: $APP_DIR"

    if ! unit_is_installed "$TELEGRAM_UNIT" || ! unit_is_installed "$WEB_UNIT"; then
        warn "Службы не установлены — сначала пункт 1 (установить / обновить)"
        return 1
    fi

    if ! update_bot_code; then
        return 1
    fi

    # После обновления кода с новым pyproject — подтянуть зависимости
    if ! python_deps_ok; then
        warn "Зависимости Python устарели после обновления — ставим заново"
        ensure_venv
        ensure_python_deps || warn "pip install не удался — выполните пункт 1"
    fi

    fix_permissions
    restart_services
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

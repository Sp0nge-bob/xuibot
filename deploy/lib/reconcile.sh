# shellcheck shell=bash
# Идемпотентная установка / обновление (пункт 1 меню)

# Дефолт upstream (форки: GIT_REMOTE=… перед ctl или в deploy/state.env)
DEFAULT_GIT_REMOTE="${DEFAULT_GIT_REMOTE:-https://github.com/Sp0nge-bob/xuibot.git}"

print_no_git_help() {
    warn "Каталог $APP_DIR не является git-репозиторием (нет $APP_DIR/.git)."
    warn "Пункт 2 делает «git pull + рестарт» — без .git обновить код нельзя."
    echo
    printf '%s\n' "Что обычно случилось: бот скопировали архивом/rsync без папки .git."
    echo
    printf '%s\n' "Вариант A (рекомендуется) — привязать этот каталог к GitHub:"
    printf '%s\n' "  sudo GIT_REMOTE=https://github.com/Sp0nge-bob/xuibot.git bash deploy/vpn-bot-ctl.sh update"
    printf '%s\n' "  (скрипт предложит git init + fetch; .env и data/ не трогает — они в .gitignore)"
    echo
    printf '%s\n' "Вариант B — клон с нуля с сохранением данных:"
    printf '%s\n' "  sudo systemctl stop vpn-bot-telegram vpn-bot-web"
    printf '%s\n' "  sudo mv $APP_DIR ${APP_DIR}.bak"
    printf '%s\n' "  sudo git clone $DEFAULT_GIT_REMOTE $APP_DIR"
    printf '%s\n' "  sudo cp ${APP_DIR}.bak/.env $APP_DIR/ 2>/dev/null || true"
    printf '%s\n' "  sudo cp -a ${APP_DIR}.bak/data $APP_DIR/ 2>/dev/null || true"
    printf '%s\n' "  cd $APP_DIR && sudo bash deploy/vpn-bot-ctl.sh   # пункт 1"
    echo
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

resolve_git_remote() {
    # GIT_REMOTE из окружения → state.env → origin → дефолт
    if [[ -n "${GIT_REMOTE:-}" ]]; then
        echo "$GIT_REMOTE"
        return
    fi
    if [[ -f "$STATE_FILE" ]]; then
        # shellcheck disable=SC1090
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

save_git_remote_to_state() {
    local remote="$1"
    [[ -n "$remote" ]] || return 0
    mkdir -p "$DEPLOY_DIR"
    if [[ -f "$STATE_FILE" ]] && grep -qE '^GIT_REMOTE=' "$STATE_FILE" 2>/dev/null; then
        sed -i.bak "s|^GIT_REMOTE=.*|GIT_REMOTE=$remote|" "$STATE_FILE" 2>/dev/null \
            || sed -i '' "s|^GIT_REMOTE=.*|GIT_REMOTE=$remote|" "$STATE_FILE" 2>/dev/null || true
        rm -f "${STATE_FILE}.bak" 2>/dev/null || true
    elif [[ -f "$STATE_FILE" ]]; then
        printf '\nGIT_REMOTE=%s\n' "$remote" >>"$STATE_FILE"
    fi
}

bootstrap_git_repo() {
    # Превращает каталог без .git в clone origin (tracked файлы с GitHub;
    # .env / data / .venv обычно в .gitignore — сохраняются).
    local remote="${1:-}"
    local branch="${GIT_BRANCH:-main}"
    local confirm=""

    command -v git >/dev/null 2>&1 || die "git не установлен: apt-get install -y git"

    if [[ -z "$remote" ]]; then
        remote="$(resolve_git_remote)"
    fi

    warn "Будет выполнено: git init + fetch + checkout -B $branch origin/$branch"
    warn "Отслеживаемые файлы перезапишутся с GitHub. Не трогаем: .env, data/, .venv (если в .gitignore)."
    printf 'Remote: %s\n' "$remote"

    if [[ -t 0 || -r /dev/tty ]]; then
        read -r -p "Привязать $APP_DIR к git и скачать код? [y/N]: " confirm </dev/tty
        if [[ ! "$confirm" =~ ^([yY]|yes|д|да)$ ]]; then
            warn "Отменено"
            return 1
        fi
    elif [[ "${GIT_BOOTSTRAP:-}" != "1" && "${GIT_BOOTSTRAP:-}" != "yes" ]]; then
        warn "Неинтерактивно: задайте GIT_BOOTSTRAP=1 и GIT_REMOTE=… для авто-привязки"
        return 1
    fi

    (
        set -e
        cd "$APP_DIR"
        if [[ ! -d .git ]]; then
            git init -b "$branch" 2>/dev/null || { git init; git checkout -B "$branch"; }
        fi
        if git remote get-url origin >/dev/null 2>&1; then
            git remote set-url origin "$remote"
        else
            git remote add origin "$remote"
        fi
        git fetch --depth=1 origin "$branch"
        # -f: выровнять дерево под origin (локальные правки tracked-файлов будут сброшены)
        git checkout -B "$branch" "origin/$branch" --force
        git branch --set-upstream-to="origin/$branch" "$branch" 2>/dev/null || true
    ) || {
        warn "Не удалось привязать git. Проверьте URL, сеть и доступ к репозиторию."
        return 1
    }

    save_git_remote_to_state "$remote"
    fix_repo_ownership_for_git
    ok "Репозиторий привязан: $(git -C "$APP_DIR" rev-parse --short HEAD) ← $remote"
    return 0
}

ensure_git_repo_for_update() {
    if [[ -d "$APP_DIR/.git" ]]; then
        return 0
    fi
    print_no_git_help
    if bootstrap_git_repo "$(resolve_git_remote)"; then
        return 0
    fi
    return 1
}

git_pull_repo() {
    if [[ ! -d "$APP_DIR/.git" ]]; then
        ensure_git_repo_for_update || return 1
    fi
    fix_repo_ownership_for_git
    git_discard_deploy_script_drift
    log "git pull в $APP_DIR"
    local before after
    before="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if ! git -C "$APP_DIR" pull --ff-only; then
        warn "git pull не удался — проверьте сеть, доступ к origin и локальные изменения"
        warn "Подсказка: git -C $APP_DIR status ; git -C $APP_DIR remote -v"
        return 1
    fi
    after="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if [[ "$before" == "$after" ]]; then
        ok "Код уже актуален ($after)"
    else
        ok "Код обновлён: $before → $after"
    fi
    return 0
}

cmd_update_bot() {
    require_root
    load_config
    log "Обновление бота: git pull + перезапуск служб"
    log "Каталог: $APP_DIR"

    if ! unit_is_installed "$TELEGRAM_UNIT" || ! unit_is_installed "$WEB_UNIT"; then
        warn "Службы не установлены — сначала пункт 1 (установить / обновить)"
        return 1
    fi

    if ! git_pull_repo; then
        return 1
    fi

    # После обновления кода с новым pyproject — подтянуть зависимости (быстро, если уже ок)
    if ! python_deps_ok; then
        warn "Зависимости Python устарели после pull — ставим заново"
        ensure_venv
        ensure_python_deps || warn "pip install не удался — выполните пункт 1"
    fi

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
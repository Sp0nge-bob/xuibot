# shellcheck shell=bash
# Идемпотентная установка / обновление (пункт 1 меню)

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

git_pull_repo() {
    [[ -d "$APP_DIR/.git" ]] || die "Не git-репозиторий: $APP_DIR/.git"
    fix_repo_ownership_for_git
    git_discard_deploy_script_drift
    log "git pull в $APP_DIR"
    local before after
    before="$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
    if ! git -C "$APP_DIR" pull --ff-only; then
        warn "git pull не удался — проверьте сеть, доступ к origin и локальные изменения"
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
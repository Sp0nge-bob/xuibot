# shellcheck shell=bash
# Идемпотентная установка / обновление (пункт 1 меню)

cmd_reconcile() {
    require_root
    load_config
    log "Каталог: $APP_DIR"
    log "Пользователь: $SERVICE_USER"

    fix_repo_ownership_for_git
    validate_project
    ensure_env_file
    fix_env_for_systemd
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
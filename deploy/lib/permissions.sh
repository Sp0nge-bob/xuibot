# shellcheck shell=bash
# Права: root владеет .git, vpnbot — runtime; /root — traverse для vpnbot

fix_repo_ownership_for_git() {
    if [[ -d "$APP_DIR/.git" ]]; then
        chown -R root:root "$APP_DIR/.git"
        git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
    fi
}

fix_root_home_access() {
    # /root по умолчанию 700 — vpnbot не может cd в /root/vpn-platega-bot (CHDIR Permission denied)
    if [[ "$APP_DIR" == /root/* ]]; then
        warn "Проект в /root — открываем traverse для $SERVICE_USER (chmod o+x /root)"
        chmod 711 /root
    fi
}

fix_permissions() {
    log "Права: runtime → $SERVICE_USER, .git → root"
    mkdir -p "$APP_DIR/data/logs" "$APP_DIR/.cache/pip"
    fix_repo_ownership_for_git
    fix_root_home_access

    # Каталог проекта — root, но читаем/проходим всем (vpnbot заходит через /root с o+x)
    chown root:root "$APP_DIR"
    chmod u+rwx,go+rx "$APP_DIR"

    chmod -R a+rX "$APP_DIR"
    find "$APP_DIR" -type d -exec chmod a+rx {} + 2>/dev/null || true
    find "$APP_DIR" -type f -exec chmod a+r {} + 2>/dev/null || true

    if [[ -d "$APP_DIR/.git" ]]; then
        chown -R root:root "$APP_DIR/.git"
    fi

    if [[ -d "$APP_DIR/.venv" ]]; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.venv"
        chmod -R u+rwX,go+rX "$APP_DIR/.venv"
    fi
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/.cache"
    chmod -R u+rwX,go+rX "$APP_DIR/data" "$APP_DIR/.cache" 2>/dev/null || true

    if [[ -f "$APP_DIR/.env" ]]; then
        chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
    fi
}

verify_service_user_access() {
    local py="$APP_DIR/.venv/bin/python"
    log "Проверка: $SERVICE_USER может войти в $APP_DIR и импортировать loguru"

    if ! sudo -u "$SERVICE_USER" -- bash -c "cd '$APP_DIR' && pwd" >/dev/null 2>&1; then
        warn "Тест cd от $SERVICE_USER не прошёл"
        fix_root_home_access
        chmod u+rwx,go+rx "$APP_DIR"
        if ! sudo -u "$SERVICE_USER" -- bash -c "cd '$APP_DIR' && pwd" >/dev/null 2>&1; then
            die "$SERVICE_USER не может войти в $APP_DIR — перенесите проект в /opt/vpn-bot"
        fi
    fi

    if ! sudo -u "$SERVICE_USER" -- "$py" -c "import loguru, aiogram, fastapi" 2>/dev/null; then
        warn "Импорт от $SERVICE_USER не прошёл — переустанавливаем зависимости"
        return 1
    fi

    if ! sudo -u "$SERVICE_USER" -- bash -c "cd '$APP_DIR' && '$py' -c 'from config.settings import settings'" 2>/dev/null; then
        warn "Ошибка в .env — проверьте DEFAULT_SUBSCRIPTION_INBOUNDS (через запятую)"
        sudo -u "$SERVICE_USER" -- bash -c "cd '$APP_DIR' && '$py' -c 'from config.settings import settings'" 2>&1 | tail -n 8 >&2 || true
        return 1
    fi

    ok "Доступ $SERVICE_USER OK"
    return 0
}
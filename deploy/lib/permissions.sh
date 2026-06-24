# shellcheck shell=bash
# Права: root владеет .git, vpnbot — runtime

fix_repo_ownership_for_git() {
    if [[ -d "$APP_DIR/.git" ]]; then
        chown -R root:root "$APP_DIR/.git"
        git config --global --add safe.directory "$APP_DIR" 2>/dev/null || true
    fi
    chown root:root "$APP_DIR" 2>/dev/null || true
}

fix_permissions() {
    log "Права: runtime → $SERVICE_USER, .git → root"
    mkdir -p "$APP_DIR/data/logs" "$APP_DIR/.cache/pip"
    fix_repo_ownership_for_git

    chmod -R a+rX "$APP_DIR"
    find "$APP_DIR" -type d -exec chmod a+x {} + 2>/dev/null || true

    if [[ -d "$APP_DIR/.venv" ]]; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.venv"
    fi
    chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/data" "$APP_DIR/.cache"

    if [[ -f "$APP_DIR/.env" ]]; then
        chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
    fi
}
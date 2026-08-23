# shellcheck shell=bash
# redis-server для FSM aiogram (REDIS_URL)

redis_ping_ok() {
    command -v redis-cli >/dev/null 2>&1 \
        && redis-cli ping 2>/dev/null | grep -q PONG
}

ensure_redis_server() {
    if redis_ping_ok; then
        ok "Redis: PONG"
        return 0
    fi

    if ! command -v apt-get >/dev/null 2>&1; then
        warn "Redis не запущен; apt-get недоступен — установите redis-server вручную"
        return 1
    fi

    log "Установка redis-server (Debian/Ubuntu)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y redis-server || {
        warn "Не удалось установить redis-server"
        return 1
    }

    systemctl enable redis-server 2>/dev/null || true
    systemctl start redis-server 2>/dev/null || true

    if redis_ping_ok; then
        ok "Redis установлен и отвечает PONG"
        return 0
    fi

    warn "redis-server установлен, но redis-cli ping не PONG"
    return 1
}

ensure_redis_url_in_env() {
    local env_file="$APP_DIR/.env"

    [[ -f "$env_file" ]] || return 0
    if grep -Eq '^[[:space:]]*REDIS_URL[[:space:]]*=' "$env_file"; then
        return 0
    fi
    if ! redis_ping_ok; then
        warn "REDIS_URL не добавлен в .env — Redis недоступен"
        return 0
    fi

    log "Добавляем REDIS_URL в .env (FSM → Redis, меньше RAM)"
    {
        printf '\n# FSM aiogram — автодобавлено deploy/vpn-bot-ctl.sh\n'
        printf 'REDIS_URL=redis://127.0.0.1:6379/0\n'
    } >>"$env_file"
    ok "REDIS_URL=redis://127.0.0.1:6379/0"
}

show_redis_status() {
    echo
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    printf '  %s\n' "redis-server (FSM)"
    printf '%s\n' "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if redis_ping_ok; then
        ok "PONG"
        if command -v systemctl >/dev/null 2>&1; then
            if systemctl is-active --quiet redis-server 2>/dev/null; then
                ok "systemd: active"
            else
                warn "systemd: redis-server не active (но ping OK)"
            fi
        fi
    else
        warn "не отвечает — бот использует MemoryStorage, если REDIS_URL пуст"
    fi

    if [[ -f "${APP_DIR:-}/.env" ]]; then
        if grep -Eq '^[[:space:]]*REDIS_URL[[:space:]]*=[[:space:]]*[^[:space:]#]+' "$APP_DIR/.env"; then
            ok "REDIS_URL задан в .env"
        else
            warn "REDIS_URL не задан — FSM в RAM (MemoryStorage)"
        fi
    fi
}

# Полное удаление redis-server (для purge --with-redis).
# Останавливает службу и снимает пакет; предупреждает, если PM неизвестен.
purge_redis_server() {
    log "Удаление Redis (stop + disable + пакет)…"

    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now redis-server 2>/dev/null || true
        systemctl disable --now redis 2>/dev/null || true
        systemctl stop redis-server 2>/dev/null || true
        systemctl stop redis 2>/dev/null || true
    fi
    if command -v service >/dev/null 2>&1; then
        service redis-server stop 2>/dev/null || true
        service redis stop 2>/dev/null || true
    fi

    local removed=0
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get remove -y --purge redis-server redis-tools 2>/dev/null || \
            apt-get remove -y --purge redis-server 2>/dev/null || true
        apt-get autoremove -y 2>/dev/null || true
        removed=1
    elif command -v dnf >/dev/null 2>&1; then
        dnf remove -y redis 2>/dev/null || true
        removed=1
    elif command -v yum >/dev/null 2>&1; then
        yum remove -y redis 2>/dev/null || true
        removed=1
    elif command -v apk >/dev/null 2>&1; then
        apk del redis 2>/dev/null || true
        removed=1
    elif command -v zypper >/dev/null 2>&1; then
        zypper --non-interactive remove -y redis 2>/dev/null || true
        removed=1
    elif command -v pacman >/dev/null 2>&1; then
        pacman -Rns --noconfirm redis 2>/dev/null || true
        removed=1
    else
        warn "Неизвестный пакетный менеджер — удалите redis вручную"
    fi

    if command -v redis-cli >/dev/null 2>&1 && redis_ping_ok; then
        warn "Redis всё ещё отвечает на ping — пакет мог не удалиться"
        return 1
    fi

    if [[ "$removed" -eq 1 ]]; then
        ok "Redis снят (служба остановлена, пакет удалён где возможно)"
    else
        warn "Автоудаление Redis не выполнено"
        return 1
    fi
    return 0
}
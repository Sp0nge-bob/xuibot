# shellcheck shell=bash
# venv, pip, зависимости (PEP 668)

find_system_python() {
    local c
    for c in python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

ensure_os_python_packages() {
    if ! command -v apt-get >/dev/null 2>&1; then
        return 0
    fi
    log "Системные пакеты Python (Debian/Ubuntu)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y \
        python3-venv python3-pip python3-full \
        python3.11-venv python3.11-full 2>/dev/null \
        || apt-get install -y python3-venv python3-pip python3-full
}

venv_python() {
    echo "$APP_DIR/.venv/bin/python"
}

venv_is_healthy() {
    local py
    py="$(venv_python)"
    [[ -x "$py" ]] || return 1
    "$py" -c 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)' 2>/dev/null || return 1
    "$py" -m pip --version >/dev/null 2>&1 || return 1
    return 0
}

ensure_venv() {
    local venv_py py_cmd
    venv_py="$(venv_python)"
    py_cmd="$(find_system_python)" || die "Python 3.11+ не найден"

    ensure_os_python_packages

    if [[ -d "$APP_DIR/.venv" ]] && ! venv_is_healthy; then
        warn "Битый .venv — пересоздаём"
        rm -rf "$APP_DIR/.venv"
    fi

    if venv_is_healthy; then
        ok "Virtualenv: $APP_DIR/.venv"
        return
    fi

    log "Создаём virtualenv: $APP_DIR/.venv"
    "$py_cmd" -m venv "$APP_DIR/.venv"
    [[ -x "$venv_py" ]] || die "Не удалось создать venv"

    if ! "$venv_py" -m pip --version >/dev/null 2>&1; then
        log "Bootstrap pip (ensurepip)"
        "$venv_py" -m ensurepip --upgrade
    fi

    venv_is_healthy || die "venv без pip — установите python3-full"
    ok "Virtualenv создан"
}

python_deps_ok() {
    local py
    py="$(venv_python)"
    "$py" -c "import aiogram, fastapi, loguru" 2>/dev/null
}

run_venv_pip() {
    local py
    py="$(venv_python)"
    env PIP_DISABLE_PIP_VERSION_CHECK=1 \
        "$py" -m pip "$@"
}

install_python_deps() {
    log "pip install -e . (1–3 мин)"
    run_venv_pip install -U pip wheel
    run_venv_pip install -e "$APP_DIR" || return 1
    python_deps_ok
}

ensure_python_deps() {
    venv_is_healthy || die "venv не готов"

    if python_deps_ok; then
        ok "Зависимости Python установлены"
        return 0
    fi

    install_python_deps || die "Не удалось установить зависимости (интернет?)"
    ok "Зависимости установлены"
}

ensure_python_deps_as_service_user() {
    local py="$APP_DIR/.venv/bin/python"
    if sudo -u "$SERVICE_USER" -- "$py" -c "import loguru, aiogram, fastapi" 2>/dev/null; then
        return 0
    fi
    warn "Повтор pip install от root (после смены прав на .venv)"
    install_python_deps || return 1
    sudo -u "$SERVICE_USER" -- "$py" -c "import loguru, aiogram, fastapi" 2>/dev/null
}
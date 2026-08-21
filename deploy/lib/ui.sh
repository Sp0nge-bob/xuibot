# shellcheck shell=bash
# Цвета и оформление CLI (отключается: NO_COLOR=1 или не-TTY)

_ui_init() {
    if [[ -n "${NO_COLOR:-}" ]] || [[ ! -t 1 ]]; then
        C_RESET="" C_BOLD="" C_DIM=""
        C_CYAN="" C_GREEN="" C_YELLOW="" C_RED="" C_BLUE="" C_MAGENTA=""
        UI_COLOR=0
        return
    fi
    C_RESET=$'\033[0m'
    C_BOLD=$'\033[1m'
    C_DIM=$'\033[2m'
    C_CYAN=$'\033[36m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_RED=$'\033[31m'
    C_BLUE=$'\033[34m'
    C_MAGENTA=$'\033[35m'
    UI_COLOR=1
}

_ui_init

# Обрезает/паддит строку до ширины (символы, не байты — достаточно для ASCII/цифр)
ui_pad() {
    local text="$1" width="${2:-40}"
    # убрать ANSI для подсчёта длины
    local plain
    plain="$(printf '%s' "$text" | sed 's/\x1b\[[0-9;]*m//g')"
    local len=${#plain}
    if (( len > width )); then
        printf '%s' "${plain:0:width-1}…"
        return
    fi
    printf '%s%*s' "$plain" $((width - len)) ''
}

ui_rule() {
    local w="${1:-46}" i
    printf '%s' "${C_DIM}"
    for ((i = 0; i < w; i++)); do printf '─'; done
    printf '%s\n' "${C_RESET}"
}

ui_banner() {
    local title="${1:-VPN Bot}"
    local subtitle="${2:-}"
    printf '\n'
    printf '%s╭──────────────────────────────────────────────╮%s\n' "$C_CYAN" "$C_RESET"
    printf '%s│%s  %s%-42s%s %s│%s\n' \
        "$C_CYAN" "$C_RESET" "$C_BOLD" "$(ui_pad "$title" 42)" "$C_RESET" "$C_CYAN" "$C_RESET"
    if [[ -n "$subtitle" ]]; then
        printf '%s│%s  %s%-42s%s %s│%s\n' \
            "$C_CYAN" "$C_RESET" "$C_DIM" "$(ui_pad "$subtitle" 42)" "$C_RESET" "$C_CYAN" "$C_RESET"
    fi
    printf '%s╰──────────────────────────────────────────────╯%s\n' "$C_CYAN" "$C_RESET"
}

ui_menu_item() {
    local num="$1" label="$2" hint="${3:-}"
    printf '  %s%2s%s  %s%-28s%s' "$C_BOLD$C_CYAN" "$num" "$C_RESET" "$C_BOLD" "$label" "$C_RESET"
    if [[ -n "$hint" ]]; then
        printf '  %s%s%s' "$C_DIM" "$hint" "$C_RESET"
    fi
    printf '\n'
}

ui_menu_sep() {
    printf '  %s···············%s\n' "$C_DIM" "$C_RESET"
}

ui_kv() {
    local k="$1" v="$2"
    printf '  %s%-12s%s %s\n' "$C_DIM" "$k" "$C_RESET" "$v"
}

ui_header() {
    printf '\n%s▸ %s%s\n' "$C_BLUE$C_BOLD" "$*" "$C_RESET"
}

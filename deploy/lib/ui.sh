# shellcheck shell=bash
# Charm/gum-inspired UI для deploy CLI.
# NO_COLOR=1 или не-TTY → без ANSI.
# Не UTF-8 → ASCII-рамки (без артефактов в C-locale).

_ui_init() {
    UI_COLOR=0
    UI_UTF8=0
    C_RESET="" C_BOLD="" C_DIM=""
    C_CYAN="" C_GREEN="" C_YELLOW="" C_RED="" C_BLUE="" C_MAGENTA="" C_WHITE=""

    if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
        UI_COLOR=1
        C_RESET=$'\033[0m'
        C_BOLD=$'\033[1m'
        C_DIM=$'\033[2m'
        # Prefer 16-color basics — fewer artifacts than 256-color on old SSH
        C_CYAN=$'\033[36m'
        C_GREEN=$'\033[32m'
        C_YELLOW=$'\033[33m'
        C_RED=$'\033[31m'
        C_BLUE=$'\033[34m'
        C_MAGENTA=$'\033[35m'
        C_WHITE=$'\033[37m'
    fi

    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
        *UTF-8*|*utf8*|*UTF8*) UI_UTF8=1 ;;
    esac
    # Many VPS set LANG empty but terminal is UTF-8
    if [[ "$UI_UTF8" -eq 0 && -n "${TERM:-}" && "${TERM}" != "dumb" ]]; then
        if locale charmap 2>/dev/null | grep -qi 'utf-8'; then
            UI_UTF8=1
        fi
    fi

    if [[ "$UI_UTF8" -eq 1 ]]; then
        UI_TL='╭' UI_TR='╮' UI_BL='╰' UI_BR='╯' UI_H='─' UI_V='│'
        UI_BULLET='›'
        UI_DOT='·'
        UI_STAR='★'
    else
        UI_TL='+' UI_TR='+' UI_BL='+' UI_BR='+' UI_H='-' UI_V='|'
        UI_BULLET='>'
        UI_DOT='-'
        UI_STAR='*'
    fi
}

_ui_init

ui_plain() {
    printf '%s' "$1" | sed 's/\x1b\[[0-9;]*m//g'
}

# Display width: prefer wc -m (chars), fallback ${#}
ui_chars() {
    local s="$1" n
    n="$(printf '%s' "$s" | wc -m 2>/dev/null | tr -d '[:space:]')"
    if [[ -z "$n" || "$n" == "0" ]]; then
        n=${#s}
    fi
    printf '%s' "$n"
}

ui_pad() {
    local text="$1" width="${2:-42}"
    local plain len pad
    plain="$(ui_plain "$text")"
    len="$(ui_chars "$plain")"
    if (( len > width )); then
        printf '%s' "$plain"
        return
    fi
    pad=$((width - len))
    printf '%s%*s' "$plain" "$pad" ''
}

ui_repeat() {
    local ch="$1" n="$2" i
    for ((i = 0; i < n; i++)); do printf '%s' "$ch"; done
}

# Card:
# ╭── VPN Bot ────────────────────╮
# │  title (42)                     │
# │  subtitle                       │
# ╰────────────────────────────────╯
ui_banner() {
    local title="${1:-ctl}"
    local subtitle="${2:-}"
    local inner=44
    local top_fill

    printf '\n'
    # Top: TL + line + space + brand + space + fill + TR
    # Brand " VPN Bot " = 9 chars
    printf '%s%s' "$C_CYAN" "$UI_TL"
    ui_repeat "$UI_H" 2
    printf '%s %sVPN Bot%s %s' "$C_RESET" "$C_BOLD$C_WHITE" "$C_RESET$C_CYAN" ""
    # remaining: inner+2 border spaces - 2 - 9 = roughly
    top_fill=$((inner - 7))
    (( top_fill < 4 )) && top_fill=4
    ui_repeat "$UI_H" "$top_fill"
    printf '%s%s\n' "$UI_TR" "$C_RESET"

    printf '%s%s%s %s%s%s %s%s%s\n' \
        "$C_CYAN" "$UI_V" "$C_RESET" \
        "$C_BOLD$C_WHITE" "$(ui_pad "$title" "$inner")" "$C_RESET" \
        "$C_CYAN" "$UI_V" "$C_RESET"

    if [[ -n "$subtitle" ]]; then
        printf '%s%s%s %s%s%s %s%s%s\n' \
            "$C_CYAN" "$UI_V" "$C_RESET" \
            "$C_DIM" "$(ui_pad "$subtitle" "$inner")" "$C_RESET" \
            "$C_CYAN" "$UI_V" "$C_RESET"
    fi

    printf '%s%s' "$C_CYAN" "$UI_BL"
    ui_repeat "$UI_H" $((inner + 2))
    printf '%s%s\n' "$UI_BR" "$C_RESET"
}

ui_section() {
    printf '\n  %s%s%s\n' "$C_DIM" "$1" "$C_RESET"
}

# ›  2  Релиз (stable)              GitHub Release ★
ui_menu_item() {
    local num="$1" label="$2" hint="${3:-}"
    local lab_w=28

    printf '  %s%s%s %s%2s%s  ' \
        "$C_CYAN" "$UI_BULLET" "$C_RESET" \
        "$C_BOLD$C_CYAN" "$num" "$C_RESET"
    printf '%s%s%s' "$C_BOLD$C_WHITE" "$(ui_pad "$label" "$lab_w")" "$C_RESET"
    if [[ -n "$hint" ]]; then
        printf ' %s%s%s' "$C_DIM" "$hint" "$C_RESET"
    fi
    printf '\n'
}

ui_kv() {
    local k="$1" v="$2"
    printf '  %s%-10s%s %s\n' "$C_DIM" "$k" "$C_RESET" "$v"
}

ui_header() {
    printf '\n%s%s %s%s\n' "$C_BLUE$C_BOLD" "$UI_BULLET" "$*" "$C_RESET"
}

ui_prompt() {
    local hint="${1:-0-8}"
    printf '\n  %sВыберите%s [%s%s%s]: ' \
        "$C_BOLD" "$C_RESET" "$C_CYAN" "$hint" "$C_RESET"
}

ui_soft_clear() {
    if [[ -t 1 ]]; then
        printf '\033[H\033[2J'
    else
        printf '\n'
    fi
}

#!/usr/bin/env bash
# Обёртка — используйте deploy/vpn-bot-ctl.sh
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/vpn-bot-ctl.sh" "$@"
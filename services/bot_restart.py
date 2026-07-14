"""Перезапуск systemd-служб бота (команда /reboot)."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
from pathlib import Path

from loguru import logger

from config.settings import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SCRIPT = _PROJECT_ROOT / "deploy" / "restart-services.sh"
_TELEGRAM_UNIT = "vpn-bot-telegram.service"
_WEB_UNIT = "vpn-bot-web.service"
_POLLING_LOCK = _PROJECT_ROOT / "data" / ".polling.lock"

# Коды «успеха» при рестарте изнутри telegram-процесса (systemd шлёт SIGTERM)
_RESTART_SUCCESS_RC = {
    0,
    -signal.SIGTERM,
    -signal.SIGKILL,
    128 + signal.SIGTERM,
    128 + signal.SIGKILL,
}


def _restart_script_path() -> Path | None:
    custom = (settings.BOT_RESTART_SCRIPT or "").strip()
    if custom:
        path = Path(custom)
        return path if path.is_file() else None
    return _DEFAULT_SCRIPT if _DEFAULT_SCRIPT.is_file() else None


def _is_restart_success(rc: int) -> bool:
    return rc in _RESTART_SUCCESS_RC


async def _run_cmd(cmd: list[str], *, timeout: float = 45.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return -1, "", "timeout"
    out = (stdout or b"").decode("utf-8", errors="replace").strip()
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    return int(proc.returncode or 0), out, err


async def _restart_via_script(script: Path, *, use_sudo: bool) -> tuple[bool, str]:
    """
    Запуск restart-services.sh в отдельной сессии.
    Не ждём завершения: systemctl restart telegram убивает этот процесс (SIGTERM).
    """
    cmd = ["sudo", "-n", "bash", str(script)] if use_sudo else ["bash", str(script)]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        start_new_session=True,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
    except asyncio.TimeoutError:
        logger.info("Restart script dispatched (still running)")
        return True, "systemd restart (dispatched)"

    rc = int(proc.returncode or 0)
    err = (stderr or b"").decode("utf-8", errors="replace").strip()
    if _is_restart_success(rc):
        return True, "systemd restart"
    return False, err or f"exit {rc}"


async def _restart_via_systemctl() -> tuple[bool, str]:
    if not shutil.which("systemctl"):
        return False, "systemctl не найден"

    try:
        _POLLING_LOCK.unlink(missing_ok=True)
    except OSError as e:
        logger.debug("polling lock remove: {}", e)

    errors: list[str] = []
    for unit in (_WEB_UNIT, _TELEGRAM_UNIT):
        rc, _out, err = await _run_cmd(["systemctl", "restart", unit])
        if not _is_restart_success(rc):
            errors.append(f"{unit}: {err or rc}")

    if errors:
        return False, "; ".join(errors)
    return True, "systemctl restart"


async def trigger_bot_restart(*, reason: str = "admin") -> tuple[bool, str]:
    """Перезапустить vpn-bot-telegram и vpn-bot-web."""
    logger.warning("Bot restart requested ({})", reason)

    custom_cmd = (settings.BOT_RESTART_CMD or "").strip()
    if custom_cmd:
        rc, _out, err = await _run_cmd(["bash", "-c", custom_cmd])
        if _is_restart_success(rc):
            return True, "BOT_RESTART_CMD"
        return False, err or f"exit {rc}"

    script = _restart_script_path()
    if script and shutil.which("sudo"):
        ok, detail = await _restart_via_script(script, use_sudo=True)
        if ok:
            return True, detail
        logger.warning("sudo restart failed: {}", detail)
        return False, (
            f"{detail}. Проверьте: sudo cat /etc/sudoers.d/vpn-bot-restart"
        )

    if script and os.geteuid() == 0:
        ok, detail = await _restart_via_script(script, use_sudo=False)
        if ok:
            return True, detail

    if os.geteuid() == 0:
        ok, detail = await _restart_via_systemctl()
        if ok:
            return True, detail
        return False, detail

    return False, (
        "Нет прав на systemctl. Запустите deploy/vpn-bot-ctl.sh → пункт 1 "
        "(установит sudoers для /reboot)"
    )
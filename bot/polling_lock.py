"""Один процесс polling на машину (защита от TelegramConflictError)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from db.connection import DB_PATH

_LOCK_PATH = Path(DB_PATH).parent / ".polling.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_lock_pid() -> int | None:
    try:
        raw = _LOCK_PATH.read_text(encoding="utf-8").strip()
        return int(raw) if raw.isdigit() else None
    except (OSError, ValueError):
        return None


def acquire_polling_lock() -> None:
    """Эксклюзивный lock; бросает RuntimeError если другой экземпляр жив."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK_PATH.is_file():
        other = _read_lock_pid()
        if other is not None and _pid_alive(other):
            raise RuntimeError(
                f"Уже запущен другой polling-процесс (PID {other}). "
                f"Остановите его: pkill -f 'python.*run_bot' или kill {other}"
            )
        try:
            _LOCK_PATH.unlink()
        except OSError:
            pass
    try:
        fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError as e:
        raise RuntimeError(
            "Не удалось захватить polling lock — возможно, бот уже запущен."
        ) from e


def get_polling_lock_info() -> dict[str, int | bool | None]:
    """Состояние файла .polling.lock (без захвата)."""
    if not _LOCK_PATH.is_file():
        return {"held": False, "pid": None, "alive": False, "own_process": False}
    pid = _read_lock_pid()
    alive = _pid_alive(pid) if pid is not None else False
    return {
        "held": True,
        "pid": pid,
        "alive": alive,
        "own_process": pid == os.getpid() if pid is not None else False,
    }


def release_polling_lock() -> None:
    if not _LOCK_PATH.is_file():
        return
    owner = _read_lock_pid()
    if owner is None or owner == os.getpid():
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except OSError:
            pass
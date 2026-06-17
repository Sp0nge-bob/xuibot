"""Межпроцессная блокировка init_db (run_bot + app.py / run_all)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from db.connection import DB_PATH

_LOCK_PATH = Path(DB_PATH).parent / ".init.lock"


def acquire_init_lock(timeout_sec: float = 120.0) -> int:
    """Эксклюзивный lock-файл; возвращает fd. Блокирует до timeout_sec."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            fd = os.open(
                _LOCK_PATH,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
            os.write(fd, str(os.getpid()).encode())
            return fd
        except FileExistsError:
            time.sleep(0.25)
    raise TimeoutError(f"init_db lock timeout ({timeout_sec}s): {_LOCK_PATH}")


def release_init_lock(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass
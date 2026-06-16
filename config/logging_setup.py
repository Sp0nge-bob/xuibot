"""Настройка loguru: консоль + файл текущей сессии, хранение последних N сессий."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>"
)
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
    "{name}:{function}:{line} | {message}"
)

_current_session_log: Path | None = None


def current_session_log_path() -> Path | None:
    return _current_session_log


def _rotate_session_logs(log_dir: Path, retain: int) -> None:
    if retain < 1:
        return
    logs = sorted(
        log_dir.glob("bot_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in logs[retain:]:
        try:
            old.unlink()
        except OSError:
            pass


def setup_logging(*, level: str, log_dir: str, session_retain: int) -> Path:
    """Консоль + новый файл сессии; оставляет только последние session_retain файлов."""
    global _current_session_log

    logger.remove()

    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=_CONSOLE_FORMAT,
    )

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)

    session_name = f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    session_path = directory / session_name
    _current_session_log = session_path

    logger.add(
        session_path,
        level=level,
        format=_FILE_FORMAT,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    _rotate_session_logs(directory, session_retain)
    logger.info("Лог сессии: {} (хранится {} последних)", session_path, session_retain)
    return session_path
"""Единый лог бота: все процессы пишут в data/logs/bot.log."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_INITIALIZED = False
_LOG_FILE: Path | None = None

_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | "
    "<cyan>{extra[process]:<8}</cyan> | <level>{message}</level>"
)
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {extra[process]:<8} | "
    "{name}:{function}:{line} | {message}"
)


def is_initialized() -> bool:
    return _INITIALIZED


def current_log_path() -> Path | None:
    return _LOG_FILE


def current_session_log_path() -> Path | None:
    """Совместимость с бэкапом — тот же bot.log."""
    return _LOG_FILE


def init_logging(
    process_name: str,
    *,
    level: str = "INFO",
    log_dir: str = "data/logs",
    retain_days: int = 7,
) -> Path:
    """Один файл на все процессы; ротация в полночь, хранение retain_days дней."""
    global _INITIALIZED, _LOG_FILE

    process_name = (process_name or "app").strip()[:16]
    if _INITIALIZED:
        return _LOG_FILE or Path(log_dir) / "bot.log"

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "bot.log"
    _LOG_FILE = log_path
    _INITIALIZED = True

    logger.remove()
    logger.configure(extra={"process": process_name})

    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=_CONSOLE_FORMAT,
    )
    logger.add(
        log_path,
        level=level,
        format=_FILE_FORMAT,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        rotation="00:00",
        retention=f"{max(1, retain_days)} days",
    )

    logger.info(
        "Старт процесса «{}» → tail -f {}",
        process_name,
        log_path,
    )
    return log_path


def ensure_logging(
    process_name: str = "misc",
    *,
    level: str = "INFO",
    log_dir: str = "data/logs",
    retain_days: int = 7,
) -> Path:
    """Для скриптов: инициализировать лог, если entrypoint ещё не вызывал init_logging."""
    if _INITIALIZED:
        return _LOG_FILE or Path(log_dir) / "bot.log"
    return init_logging(
        process_name,
        level=level,
        log_dir=log_dir,
        retain_days=retain_days,
    )
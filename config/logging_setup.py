"""Логи сессии: пишем в bot.log, по завершении — botlog_YYYYMMDD_HHMMSS.log (макс. 5)."""
from __future__ import annotations

import atexit
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from loguru import logger

_INITIALIZED = False
_LOG_FILE: Path | None = None
_LOG_DIR: Path | None = None
_FILE_HANDLER_ID: int | None = None
_ARCHIVE_RETAIN = 5
_REGISTRY_NAME = ".log_session_pids.json"
_LOCK_NAME = ".log_archive.lock"

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
    return _LOG_FILE


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _registry_path(log_dir: Path) -> Path:
    return log_dir / _REGISTRY_NAME


def _read_registry(log_dir: Path) -> list[int]:
    path = _registry_path(log_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [int(x) for x in data.get("pids", [])]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return []


def _write_registry(log_dir: Path, pids: list[int]) -> None:
    path = _registry_path(log_dir)
    path.write_text(
        json.dumps({"pids": sorted(set(pids))}, ensure_ascii=False),
        encoding="utf-8",
    )


def _alive_pids(log_dir: Path) -> list[int]:
    alive = [pid for pid in _read_registry(log_dir) if _pid_alive(pid)]
    if alive != _read_registry(log_dir):
        _write_registry(log_dir, alive)
    return alive


def _register_pid(log_dir: Path) -> None:
    with _archive_lock(log_dir):
        pids = _alive_pids(log_dir)
        pid = os.getpid()
        if pid not in pids:
            pids.append(pid)
        _write_registry(log_dir, pids)


def _unregister_pid(log_dir: Path) -> list[int]:
    with _archive_lock(log_dir):
        pids = [p for p in _alive_pids(log_dir) if p != os.getpid()]
        _write_registry(log_dir, pids)
        return pids


@contextmanager
def _archive_lock(log_dir: Path) -> Iterator[None]:
    log_dir.mkdir(parents=True, exist_ok=True)
    lock_path = log_dir / _LOCK_NAME
    if sys.platform == "win32":
        import time

        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                try:
                    yield
                finally:
                    try:
                        lock_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                return
            except FileExistsError:
                time.sleep(0.05)
        yield
        return

    import fcntl

    with open(lock_path, "w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _unique_archive_path(log_dir: Path, end: datetime) -> Path:
    base = log_dir / f"botlog_{end.strftime('%Y%m%d_%H%M%S')}.log"
    if not base.exists():
        return base
    for n in range(1, 100):
        candidate = log_dir / f"botlog_{end.strftime('%Y%m%d_%H%M%S')}_{n}.log"
        if not candidate.exists():
            return candidate
    return log_dir / f"botlog_{end.strftime('%Y%m%d_%H%M%S')}_x.log"


def _prune_archives(log_dir: Path, retain: int) -> None:
    if retain < 1:
        return
    archives = sorted(
        log_dir.glob("botlog_*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in archives[retain:]:
        try:
            old.unlink()
        except OSError:
            pass


def _flush_file_sink() -> None:
    global _FILE_HANDLER_ID
    try:
        logger.complete()
    except Exception:
        pass
    if _FILE_HANDLER_ID is not None:
        try:
            logger.remove(_FILE_HANDLER_ID)
        except ValueError:
            pass
        _FILE_HANDLER_ID = None


def _archive_active_log(
    log_dir: Path,
    *,
    end_time: datetime | None = None,
    reason: str = "shutdown",
) -> Path | None:
    active = log_dir / "bot.log"
    if not active.is_file() or active.stat().st_size <= 0:
        return None

    if end_time is not None:
        end = end_time
    elif reason == "crash":
        try:
            end = datetime.fromtimestamp(active.stat().st_mtime)
        except OSError:
            end = datetime.now()
    else:
        end = datetime.now()

    with _archive_lock(log_dir):
        if not active.is_file() or active.stat().st_size <= 0:
            return None
        _flush_file_sink()
        dest = _unique_archive_path(log_dir, end)
        active.replace(dest)
        _prune_archives(log_dir, _ARCHIVE_RETAIN)
        return dest


def _recover_crashed_session(log_dir: Path) -> Path | None:
    """OOM/SIGKILL/kill -9: bot.log остался, живых PID в реестре нет."""
    active = log_dir / "bot.log"
    if not active.is_file() or active.stat().st_size <= 0:
        return None
    if _alive_pids(log_dir):
        return None
    try:
        end = datetime.fromtimestamp(active.stat().st_mtime)
    except OSError:
        end = datetime.now()
    return _archive_active_log(log_dir, end_time=end, reason="crash")


def shutdown_session_logging(*, reason: str = "shutdown") -> Path | None:
    """Вызывать при остановке процесса. Архив — когда последний процесс завершился."""
    global _INITIALIZED, _LOG_FILE

    if _LOG_DIR is None:
        return None

    remaining = _unregister_pid(_LOG_DIR)
    if remaining:
        return None

    archived = _archive_active_log(_LOG_DIR, reason=reason)
    if archived:
        print(f"Лог сессии сохранён: {archived} ({reason})", file=sys.stderr)

    _INITIALIZED = False
    _LOG_FILE = None
    return archived


def _atexit_archive() -> None:
    if not _INITIALIZED or _LOG_DIR is None:
        return
    try:
        shutdown_session_logging(reason="atexit")
    except Exception:
        pass


def init_logging(
    process_name: str,
    *,
    level: str = "INFO",
    log_dir: str = "data/logs",
    archive_retain: int | None = None,
) -> Path:
    global _INITIALIZED, _LOG_FILE, _LOG_DIR, _FILE_HANDLER_ID, _ARCHIVE_RETAIN

    process_name = (process_name or "app").strip()[:16]
    if _INITIALIZED:
        return _LOG_FILE or Path(log_dir) / "bot.log"

    if archive_retain is None:
        try:
            from config.settings import settings as _settings

            archive_retain = _settings.LOG_ARCHIVE_RETAIN
        except Exception:
            archive_retain = 5

    directory = Path(log_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _LOG_DIR = directory
    _ARCHIVE_RETAIN = max(1, int(archive_retain))

    recovered = _recover_crashed_session(directory)
    if recovered:
        print(
            f"Восстановлен лог упавшей сессии (OOM/kill): {recovered}",
            file=sys.stderr,
        )

    _register_pid(directory)

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
    _FILE_HANDLER_ID = logger.add(
        log_path,
        level=level,
        format=_FILE_FORMAT,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )

    atexit.register(_atexit_archive)

    logger.info(
        "Старт «{}» | tail -f {} | архивы: botlog_YYYYMMDD_HHMMSS.log (макс. {})",
        process_name,
        log_path,
        _ARCHIVE_RETAIN,
    )
    if recovered:
        logger.info("Предыдущая сессия сохранена в {}", recovered.name)
    return log_path


def ensure_logging(
    process_name: str = "misc",
    *,
    level: str = "INFO",
    log_dir: str = "data/logs",
    archive_retain: int | None = None,
) -> Path:
    if _INITIALIZED:
        return _LOG_FILE or Path(log_dir) / "bot.log"
    return init_logging(
        process_name,
        level=level,
        log_dir=log_dir,
        archive_retain=archive_retain,
    )
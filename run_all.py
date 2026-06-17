"""
Запуск webhook + Telegram polling одной командой.

    python run_all.py

Поднимает два процесса (как systemd в продакшене): app.py и run_bot.py.
Ctrl+C останавливает оба.

Альтернатива — один процесс: START_BOT_IN_WEBAPP=true в .env, затем python app.py
"""
from __future__ import annotations

import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_DB_PATH = _ROOT / "data" / "bot.db"
_PROCS: list[tuple[str, subprocess.Popen[bytes]]] = []
_SHUTTING_DOWN = False


def _start(script: str) -> subprocess.Popen[bytes]:
    print(f"Starting {script}...")
    return subprocess.Popen(
        [sys.executable, script],
        cwd=_ROOT,
    )


def _db_is_ready() -> bool:
    """Проверка SQLite надёжнее, чем строка в логе (loguru enqueue)."""
    if not _DB_PATH.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=3)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name IN ('users', 'xui_nodes', 'bot_settings')"
            ).fetchall()
            return len(rows) >= 3
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _log_has_db_marker() -> bool:
    log_dir = _ROOT / "data" / "logs"
    if not log_dir.is_dir():
        return False
    logs = sorted(log_dir.glob("bot_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return False
    try:
        return "Database initialized" in logs[0].read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _wait_for_db_ready(timeout_sec: float = 120) -> bool:
    deadline = time.time() + timeout_sec
    print(f"Waiting for DB init (up to {int(timeout_sec)}s)...")
    while time.time() < deadline:
        if _db_is_ready() or _log_has_db_marker():
            time.sleep(1)
            print("DB ready.")
            return True
        time.sleep(1)
    print("Warning: DB not ready in time — starting app.py anyway.")
    return False


def _shutdown(*_args: object) -> None:
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    print("\nStopping...")
    for _name, proc in _PROCS:
        if proc.poll() is None:
            proc.terminate()
    for _name, proc in _PROCS:
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    bot_proc = _start("run_bot.py")
    _PROCS.append(("run_bot.py", bot_proc))
    _wait_for_db_ready()
    web_proc = _start("app.py")
    _PROCS.append(("app.py", web_proc))
    print("Both processes started. Press Ctrl+C to stop.")

    try:
        while True:
            for name, proc in _PROCS:
                code = proc.poll()
                if code is not None:
                    print(f"{name} exited with code {code}")
                    _shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
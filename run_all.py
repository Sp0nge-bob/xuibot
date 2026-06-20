"""
Запуск webhook + Telegram polling одной командой.

    python run_all.py

Поднимает два процесса (как systemd в продакшене): app.py и run_bot.py.
Ctrl+C останавливает оба.

Альтернатива — один процесс: START_BOT_IN_WEBAPP=true в .env, затем python app.py
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from db.database import clear_init_marker

_ROOT = Path(__file__).resolve().parent
_DB_PATH = _ROOT / "data" / "bot.db"
_INIT_MARKER = _ROOT / "data" / ".init_complete"
_PROCS: list[tuple[str, subprocess.Popen[bytes]]] = []
_SHUTTING_DOWN = False
_BOT_STARTED_AT = 0.0


def _start(script: str) -> subprocess.Popen[bytes]:
    print(f"Starting {script}...")
    return subprocess.Popen(
        [sys.executable, script],
        cwd=_ROOT,
    )


def _db_is_ready() -> bool:
    """Маркер появился после старта run_bot (не от прошлого запуска)."""
    if not (_DB_PATH.is_file() and _INIT_MARKER.is_file()):
        return False
    if _BOT_STARTED_AT <= 0:
        return True
    try:
        return _INIT_MARKER.stat().st_mtime >= _BOT_STARTED_AT - 0.5
    except OSError:
        return False


def _wait_for_db_ready(timeout_sec: float = 120) -> bool:
    deadline = time.time() + timeout_sec
    print(f"Waiting for DB init (up to {int(timeout_sec)}s)...")
    while time.time() < deadline:
        if _db_is_ready():
            print("DB ready.")
            return True
        time.sleep(0.5)
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


def _preflight() -> None:
    if os.environ.get("START_BOT_IN_WEBAPP", "false").lower() in ("true", "1", "yes"):
        print(
            "Ошибка: START_BOT_IN_WEBAPP=true несовместим с run_all.py.\n"
            "Поставьте START_BOT_IN_WEBAPP=false в .env или запустите только python app.py."
        )
        sys.exit(1)


def main() -> None:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _preflight()
    clear_init_marker()
    global _BOT_STARTED_AT
    _BOT_STARTED_AT = time.time()
    bot_proc = _start("run_bot.py")
    _PROCS.append(("run_bot.py", bot_proc))
    _wait_for_db_ready()
    web_proc = _start("app.py")
    _PROCS.append(("app.py", web_proc))
    print("Both processes started. Press Ctrl+C to stop.")
    print("Логи сессии: tail -f data/logs/bot.log")
    print("Архивы после остановки: data/logs/botlog_*.log")

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
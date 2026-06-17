"""
Запуск webhook + Telegram polling одной командой.

    python run_all.py

Поднимает два процесса (как systemd в продакшене): app.py и run_bot.py.
Ctrl+C останавливает оба.

Альтернатива — один процесс: START_BOT_IN_WEBAPP=true в .env, затем python app.py
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_PROCS: list[subprocess.Popen[bytes]] = []
_SHUTTING_DOWN = False


def _start(script: str) -> subprocess.Popen[bytes]:
    print(f"Starting {script}...")
    return subprocess.Popen(
        [sys.executable, script],
        cwd=_ROOT,
    )


def _shutdown(*_args: object) -> None:
    global _SHUTTING_DOWN
    if _SHUTTING_DOWN:
        return
    _SHUTTING_DOWN = True
    print("\nStopping...")
    for proc in _PROCS:
        if proc.poll() is None:
            proc.terminate()
    for proc in _PROCS:
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Сначала run_bot — он инициализирует SQLite. Одновременный старт даёт database is locked.
    _PROCS.append(_start("run_bot.py"))
    print("Waiting for DB init (5s)...")
    time.sleep(5)
    _PROCS.append(_start("app.py"))
    print("Both processes started. Press Ctrl+C to stop.")

    try:
        while True:
            for proc in _PROCS:
                code = proc.poll()
                if code is not None:
                    name = "app.py" if proc is _PROCS[0] else "run_bot.py"
                    print(f"{name} exited with code {code}")
                    _shutdown()
            time.sleep(0.5)
    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
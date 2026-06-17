"""Проверка реакции app.py на SIGINT (Windows/Linux)."""
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKERS = (
    "Polling started",
    "SIGINT/SIGTERM",
    "Остановка бота",
    "Бот остановлен",
    "Shutdown complete",
    "Finished server process",
)


def run_case(cmd: list[str]) -> int:
    creationflags = 0
    if sys.platform.startswith("win"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    print(f"\n=== CASE: {' '.join(cmd)} ===")
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        creationflags=creationflags,
    )
    print(f"pid={proc.pid}, waiting for bot startup...")
    started = time.time()
    seen = set()
    buf = []

    try:
        while time.time() - started < 120:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                time.sleep(0.2)
                continue
            line = line.rstrip()
            buf.append(line)
            print(line)
            for m in MARKERS:
                if m in line:
                    seen.add(m)
            if "Polling started" in line:
                print("--- sending SIGINT ---")
                time.sleep(1)
                if sys.platform.startswith("win"):
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
                sigint_at = time.time()
                while time.time() - sigint_at < 30:
                    line = proc.stdout.readline()
                    if line:
                        line = line.rstrip()
                        buf.append(line)
                        print(line)
                        for m in MARKERS:
                            if m in line:
                                seen.add(m)
                    if proc.poll() is not None:
                        break
                    if "Бот остановлен" in seen and proc.poll() is not None:
                        break
                    time.sleep(0.2)
                break
        else:
            print("TIMEOUT: bot did not reach Polling started in 120s")
            proc.kill()
            return 1
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)

    print("--- summary ---")
    print("seen:", sorted(seen))
    print("exit_code:", proc.returncode)
    ok = (
        "Polling started" in seen
        and "Бот остановлен" in seen
        and "Shutdown complete" in seen
        and proc.poll() is not None
    )
    return 0 if ok else 2


def main() -> int:
    cases = [
        [sys.executable, "app.py"],
        [sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8081"],
    ]
    rc = 0
    for cmd in cases:
        code = run_case(cmd)
        if code != 0:
            rc = code
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
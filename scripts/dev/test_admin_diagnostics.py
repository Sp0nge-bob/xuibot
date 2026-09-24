"""Обёртка: юниты диагностики живут в tests/test_admin_diagnostics.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    return subprocess.call(
        [sys.executable, "-m", "pytest", str(_ROOT / "tests" / "test_admin_diagnostics.py"), "-q"],
    )


if __name__ == "__main__":
    raise SystemExit(main())

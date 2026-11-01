"""Portable runner: synthetic settings and denied outbound connections."""
import os
from pathlib import Path
import socket
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.env').exists():
    raise SystemExit('Use an isolated checkout without .env')
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
TEMP = ROOT / ".test_tmp"
TEMP.mkdir(exist_ok=True)
os.environ.update({
    "PYTEST_RUNNING": "1", "BOT_TOKEN": "123456789:synthetic-offline-token",
    "PLATEGA_MERCHANT_ID": "00000000-0000-0000-0000-000000000000",
    "PLATEGA_SECRET": "synthetic-offline-webhook-secret",
    "XUI_HOST": "https://panel.invalid/", "XUI_USERNAME": "synthetic",
    "XUI_PASSWORD": "synthetic", "SECRET_KEY": "synthetic-offline-key-for-security-regressions",
    "ENCRYPTION_KEY": "", "OLD_SECRET_KEY": "", "REDIS_URL": "",
    "DB_PATH": str(TEMP / f"offline_{uuid.uuid4().hex}.db"),
    "LOG_DIR": str(TEMP / "logs"), "WEBSITE_URL": "https://website.invalid/",
})

_original_connect = socket.socket.connect

def deny_connection(*args, **kwargs):
    # Windows builds asyncio's local wakeup pipe using socketpair's loopback shim.
    caller = sys._getframe(1)
    if (caller.f_code.co_filename == socket.__file__
            and caller.f_code.co_name == "_fallback_socketpair"):
        return _original_connect(*args, **kwargs)
    raise AssertionError("Outbound connection blocked by offline test harness")

socket.socket.connect = deny_connection
socket.socket.connect_ex = deny_connection
socket.create_connection = deny_connection

import pytest
raise SystemExit(pytest.main(sys.argv[1:]))

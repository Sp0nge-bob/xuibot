"""Текущее потребление CPU/RAM процессом бота (psutil)."""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    role: str
    cpu_percent: float
    rss_mb: float


def process_role_label() -> str:
    name = os.path.basename(sys.argv[0] or "bot").lower()
    if "run_bot" in name:
        return "Telegram"
    if name in ("app.py", "app"):
        return "Webhook"
    if "run_all" in name:
        return "run_all"
    return name.removesuffix(".py") or "bot"


def get_process_usage(*, cpu_sample_sec: float = 0.08) -> Optional[ProcessUsage]:
    try:
        import psutil
    except ImportError:
        return None

    try:
        proc = psutil.Process(os.getpid())
        with proc.oneshot():
            mem = proc.memory_info()
            cpu = proc.cpu_percent(interval=cpu_sample_sec)
        return ProcessUsage(
            pid=proc.pid,
            role=process_role_label(),
            cpu_percent=round(cpu, 1),
            rss_mb=round(mem.rss / (1024 * 1024), 1),
        )
    except Exception:
        return None


def format_process_usage_line(usage: Optional[ProcessUsage]) -> str:
    if usage is None:
        return "💻 Ресурсы: <i>недоступно</i> (установите <code>psutil</code>)"
    return (
        f"💻 CPU: <b>{usage.cpu_percent}%</b> · RAM: <b>{usage.rss_mb} MB</b> "
        f"(<code>{usage.role}</code> · pid {usage.pid})"
    )


async def fetch_process_usage_line(*, cpu_sample_sec: float = 0.08) -> str:
    usage = await asyncio.to_thread(get_process_usage, cpu_sample_sec=cpu_sample_sec)
    return format_process_usage_line(usage)
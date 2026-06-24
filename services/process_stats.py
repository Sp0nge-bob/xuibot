"""CPU/RAM каждого процесса бота (Telegram + Webhook) для анализа нагрузки на VPS."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_SCRIPT_ROLES: tuple[tuple[str, str], ...] = (
    ("run_bot.py", "Telegram"),
    ("app.py", "Webhook"),
)


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    role: str
    cpu_percent: float
    rss_mb: float


def _normalize_path(text: str) -> str:
    return text.replace("\\", "/").rstrip("/")


def _project_root() -> Path:
    return _PROJECT_ROOT


def _is_single_process_mode() -> bool:
    try:
        from config.settings import settings

        return bool(settings.START_BOT_IN_WEBAPP)
    except Exception:
        return False


def _cmdline_joined(proc: object) -> str:
    import psutil

    try:
        parts = proc.cmdline() or []
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return ""
    return _normalize_path(" ".join(parts))


def _is_project_script_process(proc: object, *, script: str, root: Path) -> bool:
    import psutil

    root_s = _normalize_path(str(root))
    joined = _cmdline_joined(proc)
    if not joined or script not in joined:
        return False
    if f"{root_s}/{script}" in joined:
        return True
    if joined.endswith(script) and root_s in joined:
        return True
    try:
        cwd = _normalize_path(proc.cwd())
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        cwd = ""
    return cwd == root_s and script in joined


def _iter_candidate_processes() -> list[object]:
    import psutil

    uid = os.getuid() if hasattr(os, "getuid") else None
    candidates: list[object] = []
    for proc in psutil.process_iter(["pid"]):
        try:
            if uid is not None and proc.uids().real != uid:
                continue
            candidates.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return candidates


def _discover_bot_processes() -> dict[str, object]:
    """role → psutil.Process (по одному на роль)."""
    import psutil

    root = _project_root()
    single = _is_single_process_mode()
    scripts = (("app.py", "Webhook + Telegram"),) if single else _SCRIPT_ROLES

    buckets: dict[str, list[object]] = {role: [] for _, role in scripts}
    for proc in _iter_candidate_processes():
        for script, role in scripts:
            if _is_project_script_process(proc, script=script, root=root):
                buckets[role].append(proc)

    picked: dict[str, object] = {}
    for role, procs in buckets.items():
        if not procs:
            continue
        try:
            picked[role] = max(procs, key=lambda p: p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return picked


def _measure_processes(
    processes: list[object],
    *,
    cpu_sample_sec: float,
) -> list[tuple[object, float, float]]:
    import psutil

    alive: list[object] = []
    for proc in processes:
        try:
            proc.cpu_percent(None)
            alive.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if cpu_sample_sec > 0:
        time.sleep(cpu_sample_sec)

    measured: list[tuple[object, float, float]] = []
    for proc in alive:
        try:
            with proc.oneshot():
                cpu = proc.cpu_percent(None)
                rss_mb = proc.memory_info().rss / (1024 * 1024)
            measured.append((proc, cpu, rss_mb))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return measured


def get_bot_processes_usage(*, cpu_sample_sec: float = 0.1) -> Optional[list[ProcessUsage]]:
    try:
        import psutil  # noqa: F401
    except ImportError:
        return None

    discovered = _discover_bot_processes()
    if not discovered:
        return []

    order = (
        ["Webhook + Telegram"]
        if _is_single_process_mode()
        else [role for _, role in _SCRIPT_ROLES]
    )
    procs_ordered = [discovered[r] for r in order if r in discovered]
    measured = _measure_processes(procs_ordered, cpu_sample_sec=cpu_sample_sec)

    by_pid = {proc.pid: (cpu, rss) for proc, cpu, rss in measured}
    usages: list[ProcessUsage] = []
    for role in order:
        proc = discovered.get(role)
        if proc is None:
            continue
        stats = by_pid.get(proc.pid)
        if stats is None:
            continue
        cpu, rss = stats
        usages.append(
            ProcessUsage(
                pid=proc.pid,
                role=role,
                cpu_percent=round(cpu, 1),
                rss_mb=round(rss, 1),
            )
        )
    return usages


def _expected_roles() -> list[str]:
    if _is_single_process_mode():
        return ["Webhook + Telegram"]
    return [role for _, role in _SCRIPT_ROLES]


def format_bot_processes_block(usages: Optional[list[ProcessUsage]]) -> str:
    if usages is None:
        return "💻 Нагрузка бота: <i>недоступно</i> (установите <code>psutil</code>)"

    expected = _expected_roles()
    by_role = {u.role: u for u in usages}
    rows: list[str] = []

    for role in expected:
        usage = by_role.get(role)
        if usage is None:
            rows.append(f"├ {role}: <i>не запущен</i>")
            continue
        rows.append(
            f"├ {usage.role}: CPU <b>{usage.cpu_percent}%</b> · "
            f"RAM <b>{usage.rss_mb} MB</b> (pid {usage.pid})"
        )

    active = [by_role[r] for r in expected if r in by_role]
    if len(active) >= 2:
        total_cpu = round(sum(u.cpu_percent for u in active), 1)
        total_ram = round(sum(u.rss_mb for u in active), 1)
        rows.append(f"└ Итого бот: CPU <b>{total_cpu}%</b> · RAM <b>{total_ram} MB</b>")
    elif rows:
        rows[-1] = rows[-1].replace("├", "└", 1)

    if not rows:
        name = os.path.basename(sys.argv[0] or "bot")
        return (
            "💻 Нагрузка бота: <i>процессы не найдены</i>\n"
            f"<i>ожидаются run_bot.py и app.py в <code>{_normalize_path(str(_project_root()))}</code> "
            f"(текущий: <code>{name}</code>)</i>"
        )

    return "💻 <b>Нагрузка бота на VPS</b>\n" + "\n".join(rows)


def build_bot_load_block(*, cpu_sample_sec: float = 0.1) -> str:
    usages = get_bot_processes_usage(cpu_sample_sec=cpu_sample_sec)
    return format_bot_processes_block(usages)


async def fetch_bot_load_block(*, cpu_sample_sec: float = 0.1) -> str:
    return await asyncio.to_thread(build_bot_load_block, cpu_sample_sec=cpu_sample_sec)


# Совместимость со старым именем
async def fetch_process_usage_line(*, cpu_sample_sec: float = 0.1) -> str:
    return await fetch_bot_load_block(cpu_sample_sec=cpu_sample_sec)
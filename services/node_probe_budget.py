"""Расчёт таймаутов для параллельной проверки нод (с учётом XUI_PANEL_CONCURRENCY)."""
from __future__ import annotations

import math

from config.settings import settings


def parallel_probe_wall_sec(
    node_count: int,
    *,
    per_node_sec: float,
    concurrency: int | None = None,
    overhead_sec: float = 8.0,
    cap_sec: float | None = None,
) -> float:
    """
    Оценка wall-time при параллельном probe с семафором.

    N нод и concurrency C → ceil(N/C) «волн» × per_node_sec.
    """
    count = max(1, int(node_count))
    conc = max(1, int(concurrency or settings.XUI_PANEL_CONCURRENCY))
    batches = math.ceil(count / conc)
    wall = float(per_node_sec) * batches + overhead_sec
    if cap_sec is not None:
        wall = min(wall, float(cap_sec))
    return max(float(per_node_sec) + 3.0, wall)
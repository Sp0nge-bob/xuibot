"""Выгрузка хвоста логов бота в .txt для админки."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

# Пресеты кнопок в UI
LOG_TAIL_PRESETS: tuple[int, ...] = (100, 500, 1000, 5000)

# Безопасные пределы (Telegram document ≤ 50 MB; оставляем запас)
LOG_TAIL_MIN_LINES = 1
LOG_TAIL_MAX_LINES = 50_000
LOG_TAIL_MAX_BYTES = 20 * 1024 * 1024  # 20 MB


@dataclass(frozen=True)
class LogTailExport:
    """Результат чтения последних N строк."""

    content: bytes
    filename: str
    lines_requested: int
    lines_returned: int
    source_path: Path
    source_size_bytes: int
    truncated_by_size: bool


def resolve_active_log_path() -> Path | None:
    """Текущий bot.log (из logging_setup или settings.LOG_DIR)."""
    try:
        from config.logging_setup import current_log_path

        path = current_log_path()
        if path is not None and path.is_file():
            return path
    except Exception:
        pass

    try:
        from config.settings import settings

        candidate = Path(settings.LOG_DIR) / "bot.log"
        if candidate.is_file():
            return candidate
    except Exception:
        pass

    fallback = Path("data/logs/bot.log")
    if fallback.is_file():
        return fallback
    return None


def parse_log_tail_count(raw: str | None) -> int | None:
    """Разобрать число строк: 100, 1_000, 5k. None если невалидно."""
    text = (raw or "").strip().lower().replace(" ", "").replace(",", "")
    if not text:
        return None
    multiplier = 1
    if text.endswith("k"):
        multiplier = 1000
        text = text[:-1]
    if not text.isdigit():
        return None
    try:
        value = int(text) * multiplier
    except ValueError:
        return None
    if value < LOG_TAIL_MIN_LINES or value > LOG_TAIL_MAX_LINES:
        return None
    return value


def _flush_log_sinks() -> None:
    try:
        logger.complete()
    except Exception:
        pass


def _read_last_lines_bytes(path: Path, n: int, *, max_bytes: int) -> tuple[list[str], bool]:
    """Прочитать последние n строк с конца файла (binary seek)."""
    if n <= 0:
        return [], False

    size = path.stat().st_size
    if size <= 0:
        return [], False

    block = 64 * 1024
    data = b""
    truncated = False
    with path.open("rb") as f:
        pos = size
        while pos > 0 and data.count(b"\n") <= n:
            if len(data) >= max_bytes:
                truncated = True
                break
            read_size = min(block, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size)
            data = chunk + data
            if len(data) > max_bytes:
                # оставить хвост max_bytes (ближе к концу файла)
                data = data[-max_bytes:]
                truncated = True
                # выровнять на начало строки
                nl = data.find(b"\n")
                if nl != -1 and nl + 1 < len(data):
                    data = data[nl + 1 :]
                break

    # splitlines() без keepends — единый \n в выводе
    raw_lines = data.splitlines()
    # если файл не заканчивается \n, последняя строка всё равно в splitlines
    if len(raw_lines) > n:
        raw_lines = raw_lines[-n:]
    lines = [line.decode("utf-8", errors="replace") for line in raw_lines]
    return lines, truncated


def export_log_tail(lines: int) -> LogTailExport:
    """Собрать .txt с последними `lines` строками активного лога."""
    requested = max(LOG_TAIL_MIN_LINES, min(int(lines), LOG_TAIL_MAX_LINES))
    path = resolve_active_log_path()
    if path is None:
        raise FileNotFoundError(
            "Файл логов не найден (ожидается data/logs/bot.log). "
            "Проверьте LOG_DIR и что бот уже писал логи."
        )

    _flush_log_sinks()
    source_size = path.stat().st_size
    body_lines, truncated = _read_last_lines_bytes(
        path, requested, max_bytes=LOG_TAIL_MAX_BYTES,
    )
    returned = len(body_lines)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bot_log_tail_{returned}_{stamp}.txt"

    header = [
        f"# VPN Platega Bot — log tail",
        f"# exported_at: {now}",
        f"# source: {path.resolve()}",
        f"# source_size_bytes: {source_size}",
        f"# lines_requested: {requested}",
        f"# lines_returned: {returned}",
        f"# truncated_by_size_limit: {str(truncated).lower()}",
        f"# max_bytes: {LOG_TAIL_MAX_BYTES}",
        "#",
        "# WARNING: may contain personal data, payment ids, panel hosts.",
        "#" + "=" * 60,
        "",
    ]
    text = "\n".join(header) + "\n".join(body_lines)
    if body_lines and not text.endswith("\n"):
        text += "\n"

    content = text.encode("utf-8")
    if len(content) > LOG_TAIL_MAX_BYTES:
        # жёсткий потолок payload
        content = content[-LOG_TAIL_MAX_BYTES:]
        nl = content.find(b"\n")
        if nl != -1:
            content = b"# ...truncated...\n" + content[nl + 1 :]
        truncated = True

    return LogTailExport(
        content=content,
        filename=filename,
        lines_requested=requested,
        lines_returned=returned,
        source_path=path,
        source_size_bytes=source_size,
        truncated_by_size=truncated,
    )

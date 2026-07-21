"""Выгрузка хвоста логов бота в .txt для админки (текущий + архивы)."""
from __future__ import annotations

import re
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

# id источника: active | arch0, arch1, …
_SOURCE_ID_RE = re.compile(r"^(?:active|arch\d+)$")
_ARCHIVE_NAME_RE = re.compile(r"^botlog_[\w.-]+\.log$")


@dataclass(frozen=True)
class LogSource:
    """Один файл логов, доступный для выгрузки."""

    id: str
    path: Path
    label: str
    is_active: bool
    size_bytes: int
    mtime: float


@dataclass(frozen=True)
class LogTailExport:
    """Результат чтения последних N строк."""

    content: bytes
    filename: str
    lines_requested: int
    lines_returned: int
    source_path: Path
    source_id: str
    source_label: str
    source_size_bytes: int
    truncated_by_size: bool


def resolve_log_dir() -> Path:
    try:
        from config.settings import settings

        return Path(settings.LOG_DIR)
    except Exception:
        return Path("data/logs")


def resolve_active_log_path() -> Path | None:
    """Текущий bot.log (из logging_setup или settings.LOG_DIR)."""
    try:
        from config.logging_setup import current_log_path

        path = current_log_path()
        if path is not None and path.is_file():
            return path
    except Exception:
        pass

    candidate = resolve_log_dir() / "bot.log"
    if candidate.is_file():
        return candidate

    fallback = Path("data/logs/bot.log")
    if fallback.is_file():
        return fallback
    return None


def list_log_sources() -> list[LogSource]:
    """
    Текущий bot.log + архивы botlog_*.log (новые первыми).
    id: active | arch0, arch1, …
    """
    sources: list[LogSource] = []
    log_dir = resolve_log_dir()
    active = resolve_active_log_path()

    if active is not None and active.is_file():
        try:
            st = active.stat()
            size = st.st_size
            mtime = st.st_mtime
        except OSError:
            size, mtime = 0, 0.0
        sources.append(
            LogSource(
                id="active",
                path=active,
                label="🟢 Текущая сессия (bot.log)",
                is_active=True,
                size_bytes=size,
                mtime=mtime,
            )
        )

    archives: list[Path] = []
    if log_dir.is_dir():
        for p in log_dir.glob("botlog_*.log"):
            if not p.is_file():
                continue
            if not _ARCHIVE_NAME_RE.match(p.name):
                continue
            # не дублировать active, если когда-то назвали иначе
            if active is not None and p.resolve() == active.resolve():
                continue
            archives.append(p)

    archives.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for i, path in enumerate(archives):
        try:
            st = path.stat()
            size = st.st_size
            mtime = st.st_mtime
        except OSError:
            continue
        # botlog_20260715_120000.log → короткая метка
        stamp = path.stem.removeprefix("botlog_")
        sources.append(
            LogSource(
                id=f"arch{i}",
                path=path,
                label=f"📦 {stamp}",
                is_active=False,
                size_bytes=size,
                mtime=mtime,
            )
        )

    return sources


def get_log_source(source_id: str) -> LogSource | None:
    """Найти источник по id (пересборка списка — актуально после prune)."""
    sid = (source_id or "").strip()
    if not _SOURCE_ID_RE.match(sid):
        return None
    for src in list_log_sources():
        if src.id == sid:
            return src
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
                data = data[-max_bytes:]
                truncated = True
                nl = data.find(b"\n")
                if nl != -1 and nl + 1 < len(data):
                    data = data[nl + 1 :]
                break

    raw_lines = data.splitlines()
    if len(raw_lines) > n:
        raw_lines = raw_lines[-n:]
    lines = [line.decode("utf-8", errors="replace") for line in raw_lines]
    return lines, truncated


def _safe_export_stem(source: LogSource) -> str:
    if source.is_active:
        return "active"
    # botlog_YYYYMMDD_HHMMSS → без префикса botlog_
    name = source.path.stem
    if name.startswith("botlog_"):
        name = name[7:]
    safe = re.sub(r"[^\w.-]+", "_", name)[:40]
    return safe or source.id


def export_log_tail(
    lines: int,
    *,
    source_id: str = "active",
) -> LogTailExport:
    """Собрать .txt с последними `lines` строками выбранного лога."""
    requested = max(LOG_TAIL_MIN_LINES, min(int(lines), LOG_TAIL_MAX_LINES))
    source = get_log_source(source_id)
    if source is None:
        if source_id == "active":
            raise FileNotFoundError(
                "Файл логов не найден (ожидается data/logs/bot.log). "
                "Проверьте LOG_DIR и что бот уже писал логи."
            )
        raise FileNotFoundError(
            f"Лог «{source_id}» не найден (архив удалён при ротации или перезапуске)."
        )

    path = source.path
    if not path.is_file():
        raise FileNotFoundError(f"Файл отсутствует: {path.name}")

    if source.is_active:
        _flush_log_sinks()

    source_size = path.stat().st_size
    body_lines, truncated = _read_last_lines_bytes(
        path, requested, max_bytes=LOG_TAIL_MAX_BYTES,
    )
    returned = len(body_lines)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _safe_export_stem(source)
    filename = f"bot_log_{stem}_tail{returned}_{stamp}.txt"

    header = [
        "# VPN Platega Bot — log tail",
        f"# exported_at: {now}",
        f"# source_id: {source.id}",
        f"# source_label: {source.label}",
        f"# source: {path.resolve()}",
        f"# is_active_session: {str(source.is_active).lower()}",
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
        source_id=source.id,
        source_label=source.label,
        source_size_bytes=source_size,
        truncated_by_size=truncated,
    )

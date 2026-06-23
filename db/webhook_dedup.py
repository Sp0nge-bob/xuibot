"""Персистентная дедупликация Platega webhook (SQLite)."""
from __future__ import annotations

from datetime import datetime, timedelta

from config.settings import settings
from db.connection import get_db


async def init_webhook_dedup() -> None:
    async with get_db() as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS webhook_events (
                tx_id TEXT NOT NULL,
                status TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                processed_at TIMESTAMP NOT NULL,
                PRIMARY KEY (tx_id, status)
            )
        """)
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_events_at "
            "ON webhook_events(processed_at)"
        )
        await db.commit()


def _cutoff_iso(ttl_sec: int) -> str:
    return (datetime.utcnow() - timedelta(seconds=max(1, ttl_sec))).isoformat()


async def try_acquire_webhook(tx_id: str, status: str) -> bool:
    """
    Зарезервировать webhook для обработки.

    False — недавно уже успешно обработан (дубликат).
    True — можно ставить в очередь.
    """
    tx = (tx_id or "").strip()
    status_u = (status or "").upper()
    if not tx or not status_u:
        return True

    ttl = int(settings.WEBHOOK_IDEMPOTENCY_TTL_SEC)
    cutoff = _cutoff_iso(ttl)
    now = datetime.utcnow().isoformat()

    async with get_db() as db:
        async with db.execute(
            "SELECT completed, processed_at FROM webhook_events "
            "WHERE tx_id = ? AND status = ?",
            (tx, status_u),
        ) as cur:
            row = await cur.fetchone()

        if row and int(row[0]) == 1 and str(row[1]) >= cutoff:
            return False

        await db.execute(
            """
            INSERT INTO webhook_events (tx_id, status, completed, processed_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(tx_id, status) DO UPDATE SET
                completed = 0,
                processed_at = excluded.processed_at
            """,
            (tx, status_u, now),
        )
        prune_before = (datetime.utcnow() - timedelta(days=7)).isoformat()
        await db.execute(
            "DELETE FROM webhook_events WHERE processed_at < ?",
            (prune_before,),
        )
        await db.commit()
    return True


async def finalize_webhook(tx_id: str, status: str, *, success: bool) -> None:
    """Успех — пометить completed; сбой — удалить, чтобы Platega могла повторить."""
    tx = (tx_id or "").strip()
    status_u = (status or "").upper()
    if not tx or not status_u:
        return

    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        if success:
            await db.execute(
                """
                UPDATE webhook_events
                SET completed = 1, processed_at = ?
                WHERE tx_id = ? AND status = ?
                """,
                (now, tx, status_u),
            )
        else:
            await db.execute(
                "DELETE FROM webhook_events WHERE tx_id = ? AND status = ?",
                (tx, status_u),
            )
        await db.commit()
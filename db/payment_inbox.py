"""Durable authenticated callback inbox with renewable, fenced processing claims."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
import uuid

from db.connection import get_db
from db.shared_schema import PAYMENT_INBOX_SQL


@dataclass(frozen=True)
class InboxClaim:
    tx_id: str
    status: str
    payload: dict
    owner: str
    attempts: int


async def init_payment_inbox() -> None:
    async with get_db() as db:
        await db.execute(PAYMENT_INBOX_SQL)
        await db.commit()


async def persist_event(tx_id: str, status: str, payload: dict) -> bool:
    """Commit first delivery before acknowledging; duplicates keep original body."""
    if not isinstance(payload, dict) or not tx_id or not status:
        raise ValueError("Invalid callback identity or body")
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO payment_inbox(tx_id,status,payload) VALUES(?,?,?) "
            "ON CONFLICT(tx_id,status) DO NOTHING", (tx_id, status, body),
        )
        await db.commit()
        return cursor.rowcount == 1


async def claim_event(*, source: str = "bot", lease_seconds: float = 120,
                      now: float | None = None) -> InboxClaim | None:
    current = time.time() if now is None else now
    owner = uuid.uuid4().hex
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                """SELECT e.tx_id,e.status,e.payload,e.attempts
                   FROM payment_inbox e
                   LEFT JOIN orders o ON o.platega_tx_id=e.tx_id
                   WHERE COALESCE(o.source,'bot')=? AND e.next_attempt_at<=?
                     AND (e.state='pending' OR (e.state='processing' AND e.lease_until<=?))
                     AND NOT EXISTS (
                         SELECT 1 FROM payment_inbox busy
                         WHERE busy.tx_id=e.tx_id AND busy.state='processing' AND busy.lease_until>?
                     )
                   ORDER BY e.next_attempt_at,e.rowid LIMIT 1""",
                (source, current, current, current),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            tx_id, status, payload, attempts = row
            await db.execute(
                "UPDATE payment_inbox SET state='processing',owner=?,lease_until=?,attempts=attempts+1,error_code=NULL "
                "WHERE tx_id=? AND status=?", (owner, current + lease_seconds, tx_id, status),
            )
            await db.commit()
        finally:
            if db.in_transaction:
                await db.rollback()
    return InboxClaim(tx_id, status, json.loads(payload), owner, int(attempts) + 1)


async def renew_claim(claim: InboxClaim, *, lease_seconds: float = 120,
                      now: float | None = None) -> bool:
    current = time.time() if now is None else now
    async with get_db() as db:
        cursor = await db.execute(
            "UPDATE payment_inbox SET lease_until=? WHERE tx_id=? AND status=? AND owner=? AND state='processing'",
            (current + lease_seconds, claim.tx_id, claim.status, claim.owner),
        )
        await db.commit()
        return cursor.rowcount == 1


async def finish_claim(claim: InboxClaim, *, state: str, error_code: str | None = None,
                       retry_delay: float = 0, now: float | None = None) -> bool:
    if state not in ("pending", "completed", "rejected"):
        raise ValueError("Invalid inbox completion state")
    current = time.time() if now is None else now
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE payment_inbox SET state=?,owner=NULL,lease_until=0,next_attempt_at=?,error_code=?
               WHERE tx_id=? AND status=? AND owner=? AND state='processing'""",
            (state, current + max(0, retry_delay), error_code, claim.tx_id, claim.status, claim.owner),
        )
        await db.commit()
        return cursor.rowcount == 1

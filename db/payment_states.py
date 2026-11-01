"""Atomic financial transitions, independent of fulfillment/revocation success."""
import time

from db.connection import get_db
from db.shared_schema import PAYMENT_STATES_SQL
from utils.utc import utc_now


async def init_payment_states() -> None:
    async with get_db() as db:
        await db.execute(PAYMENT_STATES_SQL)
        await db.commit()


async def record_refund(tx_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            "INSERT INTO payment_states(tx_id,financial_state,updated_at) VALUES(?,'refunded',?) "
            "ON CONFLICT(tx_id) DO UPDATE SET financial_state='refunded',updated_at=excluded.updated_at",
            (tx_id, time.time()),
        )
        await db.commit()


async def claim_confirmation(tx_id: str, *, reconciled_failed: bool = False) -> str:
    """Return claimed/paid/refunded/reconcile/missing; never guess legacy failed origin."""
    async with get_db() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT financial_state FROM payment_states WHERE tx_id=?", (tx_id,),
            ) as cursor:
                financial = await cursor.fetchone()
            if financial and financial[0] == "refunded":
                return "refunded"
            async with db.execute("SELECT status FROM orders WHERE platega_tx_id=?", (tx_id,)) as cursor:
                order = await cursor.fetchone()
            if order is None:
                return "missing"
            if order[0] == "paid":
                return "paid"
            if order[0] == "failed" and not reconciled_failed:
                return "reconcile"
            if order[0] not in ("pending", "failed"):
                return "reconcile"
            await db.execute(
                "INSERT INTO payment_states(tx_id,financial_state,updated_at) VALUES(?,'confirmed',?) "
                "ON CONFLICT(tx_id) DO UPDATE SET financial_state='confirmed',updated_at=excluded.updated_at "
                "WHERE payment_states.financial_state<>'refunded'", (tx_id, time.time()),
            )
            await db.execute(
                "UPDATE orders SET status='paid',paid_at=COALESCE(paid_at,?) WHERE platega_tx_id=?",
                (utc_now().isoformat(), tx_id),
            )
            await db.commit()
            return "claimed"
        finally:
            if db.in_transaction:
                await db.rollback()


async def cancel_unconfirmed(tx_id: str) -> bool:
    """Late failure/cancellation cannot overwrite an observed successful payment."""
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE orders SET status='failed'
               WHERE platega_tx_id=? AND status IN ('pending','failed')
                 AND NOT EXISTS (SELECT 1 FROM payment_states
                                 WHERE tx_id=? AND financial_state='confirmed')""",
            (tx_id, tx_id),
        )
        await db.commit()
        return cursor.rowcount == 1

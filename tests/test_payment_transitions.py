"""Financial transitions with real isolated SQLite and mocked external effects."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def payment_db(monkeypatch):
    from db import payment_states, database
    from services import payment_processor
    directory = Path(__file__).resolve().parents[1] / ".test_tmp"
    directory.mkdir(exist_ok=True)
    path = directory / f"transitions_{uuid.uuid4().hex}.db"

    @asynccontextmanager
    async def get_db():
        async with aiosqlite.connect(path, timeout=2) as connection:
            connection.row_factory = aiosqlite.Row
            yield connection

    monkeypatch.setattr(payment_states, "get_db", get_db)
    monkeypatch.setattr(database, "get_db", get_db)
    await payment_states.init_payment_states()
    async with get_db() as connection:
        await connection.execute("""CREATE TABLE orders(id INTEGER PRIMARY KEY,tg_id INTEGER,
            plan_id TEXT,amount INTEGER,platega_tx_id TEXT,status TEXT,paid_at TEXT,subscription_id INTEGER)""")
        await connection.execute("INSERT INTO orders VALUES(1,11,'1m',100,'synthetic-tx','pending',NULL,NULL)")
        await connection.commit()
    monkeypatch.setattr(payment_processor, "require_primary_for_payment", AsyncMock(return_value=True))
    monkeypatch.setattr(payment_processor, "_sync_lockdown_after_pending_end", AsyncMock())
    monkeypatch.setattr(payment_processor, "fulfill_paid_order", AsyncMock(return_value=SimpleNamespace(subscription_id=1)))
    monkeypatch.setattr(payment_processor, "notify_admins_payment_success", AsyncMock())
    monkeypatch.setattr(payment_processor, "apply_refund_reversal", AsyncMock(return_value={"action": "revoked"}))
    try:
        yield payment_states, payment_processor, get_db
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


async def status_of(get_db):
    async with get_db() as connection:
        async with connection.execute("SELECT status FROM orders") as cursor:
            return (await cursor.fetchone())[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["CANCELED", "FAILED"])
async def test_bot003_paid_is_not_overwritten_by_late_failure(payment_db, status):
    states, processor, get_db = payment_db
    assert await states.claim_confirmation("synthetic-tx") == "claimed"
    result = await processor.handle_platega_status("synthetic-tx", status, notify=False)
    assert result.handled
    assert await status_of(get_db) == "paid"


@pytest.mark.asyncio
async def test_bot003_refund_before_confirmation_is_terminal(payment_db):
    _, processor, get_db = payment_db
    await processor.handle_platega_status("synthetic-tx", "CHARGEBACKED", notify=False)
    result = await processor.handle_platega_status("synthetic-tx", "CONFIRMED", source="webhook_queue",
        callback_body={"id": "synthetic-tx", "amount": 100, "currency": "RUB"}, notify=False)
    assert result.handled
    assert await status_of(get_db) == "failed"
    processor.fulfill_paid_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot003_ambiguous_legacy_failed_is_not_reported_already_paid(payment_db):
    _, processor, get_db = payment_db
    async with get_db() as connection:
        await connection.execute("UPDATE orders SET status='failed'")
        await connection.commit()
    result = await processor.handle_platega_status("synthetic-tx", "CONFIRMED", source="webhook_queue",
        callback_body={"id": "synthetic-tx", "amount": 100, "currency": "RUB"}, notify=False)
    assert not result.already_paid
    assert not result.handled
    processor.fulfill_paid_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot003_confirmation_claim_and_cancel_are_atomic_across_connections(payment_db):
    states, _, get_db = payment_db
    await asyncio.gather(states.claim_confirmation("synthetic-tx"), states.cancel_unconfirmed("synthetic-tx"))
    # If cancellation won first, confirmation refuses legacy ambiguity; otherwise paid is stable.
    assert await status_of(get_db) in ("paid", "failed")
    async with get_db() as connection:
        async with connection.execute("SELECT financial_state FROM payment_states") as cursor:
            financial = await cursor.fetchone()
    if financial is not None:
        assert financial[0] == "confirmed"
        assert await status_of(get_db) == "paid"


@pytest.mark.asyncio
async def test_bot003_refund_fences_explicit_reconciled_confirmation(payment_db):
    states, _, get_db = payment_db
    await states.record_refund("synthetic-tx")
    assert await states.claim_confirmation("synthetic-tx", reconciled_failed=True) == "refunded"
    assert await status_of(get_db) == "pending"

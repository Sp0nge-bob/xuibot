"""Crash/restart and inter-process claim behavior on real, fictional SQLite data."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import uuid

import aiosqlite
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def inbox_db(monkeypatch):
    from db import payment_inbox
    directory = Path(__file__).resolve().parents[1] / ".test_tmp"
    directory.mkdir(exist_ok=True)
    path = directory / f"inbox_{uuid.uuid4().hex}.db"

    @asynccontextmanager
    async def get_db():
        async with aiosqlite.connect(path, timeout=2) as connection:
            yield connection

    monkeypatch.setattr(payment_inbox, "get_db", get_db)
    await payment_inbox.init_payment_inbox()
    async with get_db() as connection:
        await connection.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY,platega_tx_id TEXT,source TEXT)")
        await connection.execute("INSERT INTO orders VALUES (1,'synthetic-tx','bot')")
        await connection.commit()
    try:
        yield payment_inbox, get_db
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_bot002_committed_payload_survives_empty_process_queue(inbox_db):
    inbox, _ = inbox_db
    body = {"id": "synthetic-tx", "status": "CONFIRMED", "amount": 100, "currency": "RUB"}
    assert await inbox.persist_event("synthetic-tx", "CONFIRMED", body)
    claim = await inbox.claim_event(now=100)
    assert claim.payload == body
    assert claim.attempts == 1
    assert await inbox.finish_claim(claim, state="completed", now=100)
    assert await inbox.claim_event(now=1000) is None


@pytest.mark.asyncio
async def test_bot002_duplicate_does_not_replace_accepted_payload(inbox_db):
    inbox, _ = inbox_db
    assert await inbox.persist_event("synthetic-tx", "CONFIRMED", {"amount": 100})
    assert not await inbox.persist_event("synthetic-tx", "CONFIRMED", {"amount": 999})
    claim = await inbox.claim_event(now=100)
    assert claim.payload == {"amount": 100}


@pytest.mark.asyncio
async def test_bot002_concurrent_statuses_share_single_inflight_order(inbox_db):
    inbox, _ = inbox_db
    for status in ("CONFIRMED", "CHARGEBACKED"):
        await inbox.persist_event("synthetic-tx", status, {"status": status})
    claims = await asyncio.gather(inbox.claim_event(now=100), inbox.claim_event(now=100))
    assert sum(claim is not None for claim in claims) == 1
    first = next(claim for claim in claims if claim)
    await inbox.finish_claim(first, state="completed", now=100)
    second = await inbox.claim_event(now=100)
    assert second.status != first.status


@pytest.mark.asyncio
async def test_bot002_expired_lease_recovered_and_stale_owner_is_fenced(inbox_db):
    inbox, _ = inbox_db
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {})
    old = await inbox.claim_event(now=100, lease_seconds=10)
    assert await inbox.claim_event(now=105) is None
    current = await inbox.claim_event(now=111, lease_seconds=10)
    assert current.owner != old.owner
    assert current.attempts == 2
    assert not await inbox.renew_claim(old, now=111)
    assert not await inbox.finish_claim(old, state="completed", now=111)
    assert await inbox.finish_claim(current, state="completed", now=111)


@pytest.mark.asyncio
async def test_bot002_renewal_and_retry_deadline(inbox_db):
    inbox, _ = inbox_db
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {})
    claim = await inbox.claim_event(now=100, lease_seconds=10)
    assert await inbox.renew_claim(claim, now=109, lease_seconds=10)
    assert await inbox.claim_event(now=111) is None
    assert await inbox.finish_claim(claim, state="pending", error_code="PANEL_UNAVAILABLE", retry_delay=20, now=110)
    assert await inbox.claim_event(now=129) is None
    assert (await inbox.claim_event(now=130)).attempts == 2


@pytest.mark.asyncio
async def test_bot002_service_cannot_claim_other_source(inbox_db):
    inbox, get_db = inbox_db
    async with get_db() as connection:
        await connection.execute("UPDATE orders SET source='web'")
        await connection.commit()
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {})
    assert await inbox.claim_event(now=100) is None
    assert (await inbox.claim_event(source="web", now=100)).tx_id == "synthetic-tx"


@pytest.mark.asyncio
async def test_bot002_worker_recovers_committed_job_without_wakeup(inbox_db, monkeypatch):
    from services import fulfillment_queue as queue
    from services.payment_processor import PaymentProcessResult
    from unittest.mock import AsyncMock
    inbox, get_db = inbox_db
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {"amount": 100})
    monkeypatch.setattr(queue, "_queue", asyncio.Queue())
    monkeypatch.setattr(queue, "_shutdown", asyncio.Event())
    monkeypatch.setattr(queue, "_workers_started", False)
    monkeypatch.setattr(queue.settings, "FULFILLMENT_QUEUE_WORKERS", 1)
    handler = AsyncMock(return_value=PaymentProcessResult(handled=True))
    monkeypatch.setattr(queue, "handle_platega_status", handler)
    monkeypatch.setattr(queue, "_deliver_result", AsyncMock())
    await queue.start_fulfillment_workers()
    try:
        async def completed():
            while True:
                async with get_db() as connection:
                    async with connection.execute("SELECT state FROM payment_inbox") as cursor:
                        if await cursor.fetchone() == ("completed",):
                            return
                await asyncio.sleep(0.01)
        await asyncio.wait_for(completed(), 2)
    finally:
        await queue.stop_fulfillment_workers()
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot002_invalid_amount_rejected_and_processing_failure_scheduled(inbox_db, monkeypatch):
    from services import fulfillment_queue as queue
    from services.payment_processor import PaymentProcessResult
    from unittest.mock import AsyncMock
    inbox, get_db = inbox_db
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {"amount": 1})
    claim = await inbox.claim_event()
    monkeypatch.setattr(queue, "_process_job", AsyncMock(return_value=PaymentProcessResult(handled=False, amount_mismatch=True)))
    await queue._process_claim(claim)
    async with get_db() as connection:
        async with connection.execute("SELECT state,error_code FROM payment_inbox") as cursor:
            assert await cursor.fetchone() == ("rejected", "INVALID_PAYMENT")
    await inbox.persist_event("synthetic-tx", "CHARGEBACKED", {})
    claim = await inbox.claim_event()
    monkeypatch.setattr(queue, "_process_job", AsyncMock(side_effect=RuntimeError("synthetic secret must not persist")))
    await queue._process_claim(claim)
    async with get_db() as connection:
        async with connection.execute("SELECT state,error_code,next_attempt_at FROM payment_inbox WHERE status='CHARGEBACKED'") as cursor:
            state, error, deadline = await cursor.fetchone()
    assert (state, error) == ("pending", "PROCESSING_FAILED")
    assert deadline > 0


@pytest.mark.asyncio
async def test_bot002_lost_lease_cancels_processing_without_completing_new_owner(inbox_db, monkeypatch):
    from services import fulfillment_queue as queue
    from unittest.mock import AsyncMock
    inbox, get_db = inbox_db
    await inbox.persist_event("synthetic-tx", "CONFIRMED", {})
    old = await inbox.claim_event(now=100, lease_seconds=1)
    current = await inbox.claim_event(now=102)
    cancelled = asyncio.Event()
    async def process(job):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(queue, "_process_job", process)
    monkeypatch.setattr(queue, "_renew_lease", AsyncMock(side_effect=RuntimeError("ownership lost")))
    await asyncio.wait_for(queue._process_claim(old), 1)
    assert cancelled.is_set()
    async with get_db() as connection:
        async with connection.execute("SELECT state,owner FROM payment_inbox") as cursor:
            assert await cursor.fetchone() == ("processing", current.owner)


@pytest.mark.asyncio
async def test_bot002_http_ack_contains_real_committed_body_even_without_queue_space(inbox_db, monkeypatch):
    from config import logging_setup
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    monkeypatch.setattr(logging_setup, "init_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging_setup, "ensure_logging", lambda *args, **kwargs: None)
    import app
    inbox, _ = inbox_db
    payload = {"id": "synthetic-tx", "status": "CONFIRMED", "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=payload))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    monkeypatch.setattr(app, "enqueue_webhook_job", Mock(return_value=False))
    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 200
    assert (await inbox.claim_event()).payload == payload

"""Queue acceptance checks use only synthetic payloads and mocked integrations."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def no_process_logging_side_effects(monkeypatch):
    from config import logging_setup
    monkeypatch.setattr(logging_setup, "init_logging", lambda *args, **kwargs: None)
    monkeypatch.setattr(logging_setup, "ensure_logging", lambda *args, **kwargs: None)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["CONFIRMED", "CANCELED", "FAILED", "CHARGEBACKED"])
async def test_bot002_durable_acceptance_survives_full_wakeup_queue(monkeypatch, status):
    import app

    body = {"id": "synthetic-tx", "status": status, "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=body))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    persisted = AsyncMock(return_value=True)
    monkeypatch.setattr(app, "persist_event", persisted)
    enqueue = Mock(return_value=False)
    monkeypatch.setattr(app, "enqueue_webhook_job", enqueue)
    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 200
    persisted.assert_awaited_once_with("synthetic-tx", status, body)
    enqueue.assert_called_once_with("synthetic-tx", status, body)


@pytest.mark.asyncio
async def test_bot002_successful_enqueue_keeps_existing_ack(monkeypatch):
    import app

    body = {"id": "synthetic-tx", "status": "CONFIRMED", "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=body))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    monkeypatch.setattr(app, "persist_event", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "enqueue_webhook_job", Mock(return_value=True))
    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 200
    assert response.body == b'{"ok":true}'


@pytest.mark.asyncio
async def test_bot002_storage_failure_returns_503_without_enqueue(monkeypatch):
    import app
    body = {"id": "synthetic-tx", "status": "CONFIRMED", "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=body))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    monkeypatch.setattr(app, "persist_event", AsyncMock(side_effect=OSError("synthetic disk unavailable")))
    enqueue = Mock()
    monkeypatch.setattr(app, "enqueue_webhook_job", enqueue)
    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 503
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_bot002_unauthorized_callback_never_reaches_storage(monkeypatch):
    import app
    from fastapi import HTTPException
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock())
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=False))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    persisted = AsyncMock()
    monkeypatch.setattr(app, "persist_event", persisted)
    with pytest.raises(HTTPException) as caught:
        await app.platega_webhook(request, None, None)
    assert caught.value.status_code == 401
    persisted.assert_not_awaited()
    request.json.assert_not_awaited()

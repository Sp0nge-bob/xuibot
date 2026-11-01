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
async def test_bot002_queue_rejection_releases_claim_and_returns_503(monkeypatch, status):
    import app

    body = {"id": "synthetic-tx", "status": status, "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=body))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    monkeypatch.setattr(app, "acquire_webhook", AsyncMock(return_value=True))
    enqueue = Mock(return_value=False)
    monkeypatch.setattr(app, "enqueue_webhook_job", enqueue)
    release = AsyncMock()
    # Inject before the production fix adds this import.
    monkeypatch.setattr(app, "complete_webhook", release, raising=False)

    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 503
    enqueue.assert_called_once_with("synthetic-tx", status, body)
    release.assert_awaited_once_with("synthetic-tx", status, success=False)


@pytest.mark.asyncio
async def test_bot002_successful_enqueue_keeps_existing_ack(monkeypatch):
    import app

    body = {"id": "synthetic-tx", "status": "CONFIRMED", "amount": 100, "currency": "RUB"}
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"), headers={}, json=AsyncMock(return_value=body))
    monkeypatch.setattr(app, "verify_callback_headers", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "webhook_rate_limited", lambda *args: False)
    monkeypatch.setattr(app.db, "get_order_by_platega_tx", AsyncMock(return_value={"source": "bot"}))
    monkeypatch.setattr(app, "acquire_webhook", AsyncMock(return_value=True))
    monkeypatch.setattr(app, "enqueue_webhook_job", Mock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(app, "complete_webhook", release, raising=False)
    response = await app.platega_webhook(request, None, None)
    assert response.status_code == 200
    assert response.body == b'{"ok":true}'
    release.assert_not_awaited()

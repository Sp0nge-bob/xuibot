"""Admin network data: API contract, rendering and refresh authorization."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.types import CallbackQuery

from services import client_network as network
from bot import admin
from bot.admin_keyboards import admin_user_detail_kb
from bot.messages import admin_client_network_block


@pytest.fixture
def panel(monkeypatch):
    client = SimpleNamespace(_url=Mock(side_effect=lambda path: path), _get=AsyncMock())
    monkeypatch.setattr(network, "get_api", AsyncMock(return_value=SimpleNamespace(client=client)))
    monkeypatch.setattr(network, "_throttle", AsyncMock())
    return client


def respond(panel, obj, success=True):
    panel._get.return_value = Mock(json=Mock(return_value={"success": success, "obj": obj}))


@pytest.mark.parametrize("stamp", [1735689600, 1735689600000])
async def test_live_counters_and_timestamp_units(panel, stamp):
    respond(panel, {"email": "tg42_2", "up": 1024**3, "down": 2 * 1024**3,
                    "lastOnline": stamp})
    data = await network.get_client_network_data("tg42_2")
    assert data.status == "ok"
    assert data.last_online == datetime(2025, 1, 1, tzinfo=timezone.utc)
    text = admin_client_network_block(data)
    assert "3.00 GiB" in text
    assert "01.01.2025 04:00:00" in text
    assert "UTC+4" in text
    panel._get.assert_awaited_once_with("panel/api/clients/traffic/tg42_2", {"Accept": "application/json"})


async def test_zero_counters_are_distinct_from_missing_data(panel):
    respond(panel, {"email": "tg42", "up": 0, "down": 0, "lastOnline": 0})
    data = await network.get_client_network_data("tg42")
    text = admin_client_network_block(data)
    assert data.status == "ok"
    assert "0.00 GiB" in text
    assert "нет данных" in text


@pytest.mark.parametrize("obj", [
    {"email": "other", "up": 1, "down": 2},
    {"email": "tg42", "down": 2},
    {"email": "tg42", "up": -1, "down": 2},
    {"email": "tg42", "up": True, "down": 2},
    {"email": "tg42", "up": "bad", "down": 2},
    {"email": "tg42", "up": 1, "down": 2, "lastOnline": -1},
    [],
])
async def test_invalid_data_is_not_reported_as_zero(panel, obj):
    respond(panel, obj)
    data = await network.get_client_network_data("tg42")
    assert data.status == "unavailable"
    assert "временно недоступны" in admin_client_network_block(data)


async def test_not_found_and_rejected_response(panel):
    respond(panel, None)
    assert (await network.get_client_network_data("tg42")).status == "not_found"
    assert "не найден" in admin_client_network_block(await network.get_client_network_data("tg42"))
    respond(panel, None, success=False)
    assert (await network.get_client_network_data("tg42")).status == "unavailable"


async def test_timeout_bounds_connection_setup(monkeypatch, panel):
    async def delayed():
        await asyncio.sleep(1)
    monkeypatch.setattr(network, "NETWORK_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(network, "get_api", delayed)
    assert (await network.get_client_network_data("tg42")).status == "unavailable"
    panel._get.assert_not_awaited()


async def test_network_error_and_safe_email_encoding(panel):
    panel._get.side_effect = ConnectionError("panel unavailable")
    assert (await network.get_client_network_data("name+tag@example.test")).status == "unavailable"
    panel._url.assert_called_once_with("panel/api/clients/traffic/name%2Btag%40example.test")


async def test_refresh_is_admin_only(monkeypatch):
    monkeypatch.setattr(admin, "is_admin", lambda user_id: False)
    lookup = AsyncMock()
    monkeypatch.setattr(admin.db, "get_subscription_by_id", lookup)
    cb = CallbackQuery.model_construct(data="adm:network:42", from_user=SimpleNamespace(id=123))
    await admin.cb_admin_user_network_refresh(cb, AsyncMock())
    lookup.assert_not_awaited()


@pytest.mark.parametrize("status", ["ok", "unavailable", "not_found"])
async def test_refresh_renders_card_and_preserves_back_navigation(monkeypatch, status):
    monkeypatch.setattr(admin, "is_admin", lambda user_id: True)
    sub = {"id": 42, "tg_id": 123, "is_active": 1, "client_email": "tg123_2"}
    monkeypatch.setattr(admin.db, "get_subscription_by_id", AsyncMock(return_value=sub))
    monkeypatch.setattr(admin.db, "get_or_create_user", AsyncMock(return_value={"username": "test"}))
    monkeypatch.setattr(admin.db, "get_paid_orders_for_subscription", AsyncMock(return_value=[]))
    monkeypatch.setattr(admin, "enrich_order_with_referrer", AsyncMock(return_value=None))
    monkeypatch.setattr(admin.promo_db, "find_grant_use_heuristic_for_subscription", AsyncMock(return_value=None))
    calls = []
    async def acknowledge(*args, **kwargs):
        calls.append("ack")
    async def fetch(email):
        assert email == "tg123_2"
        calls.append("fetch")
        return network.ClientNetworkData(status, up=10, down=20, fetched_at=datetime.now(timezone.utc))
    monkeypatch.setattr(admin, "safe_cb_answer", acknowledge)
    monkeypatch.setattr(admin, "get_client_network_data", fetch)
    render = AsyncMock()
    monkeypatch.setattr(admin, "send_or_edit", render)
    state = AsyncMock()
    state.get_data.return_value = {"admin_user_from_search": True, "admin_user_picker_tg_id": 123}
    cb = CallbackQuery.model_construct(data="adm:network:42", from_user=SimpleNamespace(id=9))
    await admin.cb_admin_user_network_refresh(cb, state)
    assert calls == ["ack", "fetch"]
    text, kb = render.await_args.args[1:]
    assert "Подписка клиента" in text and "Сетевые данные" in text
    buttons = [button for row in kb.inline_keyboard for button in row]
    assert any(b.text == "Обновить сетевые данные" and b.callback_data == "adm:network:42" for b in buttons)
    assert any(b.callback_data == "adm:tg:123" for b in buttons)


async def test_inactive_subscription_never_requests_network(monkeypatch):
    monkeypatch.setattr(admin, "is_admin", lambda user_id: True)
    monkeypatch.setattr(admin.db, "get_subscription_by_id", AsyncMock(return_value={"is_active": 0}))
    fetch = AsyncMock()
    monkeypatch.setattr(admin, "get_client_network_data", fetch)
    monkeypatch.setattr(admin, "safe_cb_answer", AsyncMock())
    state = AsyncMock()
    state.get_data.return_value = {}
    cb = CallbackQuery.model_construct(data="adm:network:42", from_user=SimpleNamespace(id=9))
    await admin.cb_admin_user_network_refresh(cb, state)
    fetch.assert_not_awaited()

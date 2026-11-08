"""Тесты профилей дефолт-подписок, лимитов HWID/IP и оптимизаций 3x-ui API."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import pytest

from config.settings import settings
import db.connection as db_conn
import db.database as db_mod
import db.bot_settings as bot_settings
import db.xui_nodes as xui_nodes_mod
import db.database as db
from services.trial import claim_trial, get_trial_button_visible
from services.xui import (
    find_client_on_panel_by_sub_id,
    clear_client_hwids_on_panel,
    get_client_hwids_on_panel,
    _unified_add_client,
)


@pytest.fixture(autouse=True)
async def _setup_isolated_db(monkeypatch):
    tmp_dir = Path(__file__).resolve().parent.parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    db_file = tmp_dir / f"test_default_sub_{uuid.uuid4().hex}.db"
    await db_conn.close_connection()
    monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "DB_PATH", str(db_file))
    monkeypatch.setattr(xui_nodes_mod, "_INIT_DONE", False)
    monkeypatch.setattr(xui_nodes_mod, "_INIT_IN_PROGRESS", False)
    import services.crypto as crypto_mod
    monkeypatch.setattr(crypto_mod, "_cached_fernet", None)
    monkeypatch.setattr(crypto_mod, "_cached_candidates", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "default_sub_test_secret_key_32chars_long_123")
    await db.init_db()
    await bot_settings.init_bot_settings()
    try:
        yield
    finally:
        await db_conn.close_connection()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_default_subscription_profile_defaults():
    """Проверка значений по умолчанию, затребованных пользователем."""
    assert await bot_settings.get_trial_limit_ip() == 0
    assert await bot_settings.get_paid_limit_ip() == 0
    assert await bot_settings.get_trial_limit_hwid() == 3
    assert await bot_settings.get_paid_limit_hwid() == 0
    assert await bot_settings.get_trial_days() == 3
    assert await bot_settings.get_trial_traffic_gb() == 15
    assert await bot_settings.get_paid_default_traffic_gb() == 0
    assert await bot_settings.is_trial_enabled() is True


@pytest.mark.asyncio
async def test_update_default_subscription_settings():
    """Проверка сохранения и чтения динамических настроек дефолт-подписок."""
    assert await bot_settings.set_trial_limit_ip(2) == 2
    assert await bot_settings.get_trial_limit_ip() == 2

    assert await bot_settings.set_paid_limit_ip(10) == 10
    assert await bot_settings.get_paid_limit_ip() == 10

    assert await bot_settings.set_trial_limit_hwid(5) == 5
    assert await bot_settings.get_trial_limit_hwid() == 5

    assert await bot_settings.set_paid_limit_hwid(4) == 4
    assert await bot_settings.get_paid_limit_hwid() == 4

    assert await bot_settings.set_trial_days(7) == 7
    assert await bot_settings.get_trial_days() == 7

    assert await bot_settings.set_trial_traffic_gb(25) == 25
    assert await bot_settings.get_trial_traffic_gb() == 25

    assert await bot_settings.set_paid_default_traffic_gb(50) == 50
    assert await bot_settings.get_paid_default_traffic_gb() == 50


@pytest.mark.asyncio
async def test_inbounds_per_subscription_type():
    """Проверка раздельных списков инбаундов для trial и платных подписок."""
    await bot_settings.set_trial_inbound_ids([1, 2])
    await bot_settings.set_paid_inbound_ids([1, 2, 5, 10])

    assert await bot_settings.get_trial_inbound_ids() == [1, 2]
    assert await bot_settings.get_paid_inbound_ids() == [1, 2, 5, 10]

    # Роутинг по типу email
    trial_email = "tgfree999999"
    paid_email = "tg999999"

    assert await bot_settings.get_inbound_ids_for_email(trial_email) == [1, 2]
    assert await bot_settings.get_inbound_ids_for_email(paid_email) == [1, 2, 5, 10]

    await bot_settings.set_trial_limit_hwid(3)
    await bot_settings.set_paid_limit_hwid(0)
    assert await bot_settings.get_limit_hwid_for_email(trial_email) == 3
    assert await bot_settings.get_limit_hwid_for_email(paid_email) == 0


@pytest.mark.asyncio
async def test_trial_toggle_blocks_claiming():
    """Проверка отключения триала через is_trial_enabled."""
    await bot_settings.set_trial_enabled(False)
    assert await bot_settings.is_trial_enabled() is False

    visible = await get_trial_button_visible(77777)
    assert visible is False

    with pytest.raises(ValueError, match="отключен администратором"):
        await claim_trial(77777)

    # Включаем обратно
    await bot_settings.set_trial_enabled(True)
    assert await bot_settings.is_trial_enabled() is True
    assert await get_trial_button_visible(77777) is True


@pytest.mark.asyncio
async def test_fast_sub_id_lookup_optimization():
    """Проверка индексированного обращения к GET panel/api/clients/get/subId/{subId}."""
    mock_client = AsyncMock()
    mock_client._url = Mock(side_effect=lambda ep: f"http://mock/{ep}")
    mock_resp = Mock()
    mock_resp.json.return_value = {
        "success": True,
        "obj": [
            {
                "client": {
                    "email": "tg12345",
                    "subId": "fast-sub-123",
                    "id": "mock-uuid-1",
                    "enable": True,
                    "limitHwid": 3,
                },
                "inboundIds": [1, 13],
            }
        ]
    }
    mock_client._get = AsyncMock(return_value=mock_resp)
    mock_api = Mock(client=mock_client)

    client = await find_client_on_panel_by_sub_id(mock_api, "fast-sub-123")
    assert client is not None
    assert client.email == "tg12345"
    assert getattr(client, "limit_hwid", 0) == 3
    mock_client._get.assert_awaited_once_with(
        "http://mock/panel/api/clients/get/subId/fast-sub-123",
        {"Accept": "application/json"},
    )


@pytest.mark.asyncio
async def test_unified_add_client_includes_limit_hwid_and_no_redundant_bulk_add():
    """Проверка, что clients/add передаёт limitHwid и не делает лишний groups/bulkAdd."""
    mock_client = AsyncMock()
    mock_client._url = Mock(side_effect=lambda ep: f"http://mock/{ep}")
    mock_resp = Mock()
    mock_resp.json.return_value = {"success": True}
    mock_client._post = AsyncMock(return_value=mock_resp)
    mock_api = Mock(client=mock_client)

    with patch("services.xui._assign_client_group", new_callable=AsyncMock) as mock_bulk_add:
        client = await _unified_add_client(
            mock_api,
            email="tg88888",
            sub_id="sub-888",
            expiry_time=1700000000000,
            total_gb=15 * 1024 * 1024 * 1024,
            inbound_ids=[1, 2],
            limit_ip=2,
            limit_hwid=3,
        )

    assert client.email == "tg88888"
    assert getattr(client, "limit_hwid", 0) == 3
    mock_bulk_add.assert_not_called()

    # Проверяем payload переданный в POST /panel/api/clients/add
    call_args = mock_client._post.call_args
    posted_data = call_args[0][2]
    assert posted_data["client"]["limitHwid"] == 3
    assert posted_data["client"]["limitIp"] == 2
    assert posted_data["client"]["group"] == "telegram-bot"
    assert posted_data["inboundIds"] == [1, 2]


@pytest.mark.asyncio
async def test_clear_and_get_client_hwids():
    """Проверка очистки и получения списка HWID клиентов."""
    mock_client = AsyncMock()
    mock_client._url = Mock(side_effect=lambda ep: f"http://mock/{ep}")
    mock_client._generate_headers = Mock(return_value={"Accept": "application/json"})
    mock_client.cookies = {}
    mock_client._use_tls_verify = False
    mock_client._custom_certificate_path = None
    mock_client._check_response = AsyncMock()

    mock_resp_post = Mock()
    mock_resp_post.json.return_value = {"success": True, "obj": [{"hwid": "hwid-abc", "id": 1}]}
    mock_client._post = AsyncMock(return_value=mock_resp_post)

    mock_api = Mock(client=mock_client)

    with patch("services.xui.get_api", AsyncMock(return_value=mock_api)):
        hwids = await get_client_hwids_on_panel("tg999")
        assert len(hwids) == 1
        assert hwids[0]["hwid"] == "hwid-abc"

        with patch("httpx.AsyncClient.delete", new_callable=AsyncMock) as mock_delete:
            mock_del_resp = Mock()
            mock_del_resp.raise_for_status = Mock()
            mock_del_resp.json.return_value = {"success": True}
            mock_delete.return_value = mock_del_resp

            ok = await clear_client_hwids_on_panel("tg999")
            assert ok is True
            mock_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_inbound_options_sub_sort_index_ordering():
    from services.xui import get_inbound_options

    mock_client = Mock()
    mock_client._url = lambda p: f"http://127.0.0.1/{p}"
    mock_client._get = AsyncMock()

    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "obj": [
            {"id": 1, "remark": "Inbound 1", "protocol": "vless", "port": 443, "subSortIndex": 2},
            {"id": 2, "remark": "Inbound 2 Priority", "protocol": "vless", "port": 8443, "subSortIndex": -1},
            {"id": 3, "remark": "Inbound 3 Default", "protocol": "vless", "port": 9443, "subSortIndex": 0},
        ],
    }
    mock_client._get.return_value = mock_resp
    mock_api = Mock(client=mock_client)

    opts = await get_inbound_options(mock_api)
    assert len(opts) == 3
    # Ordered: -1 (Inbound 2) -> 1 (Inbound 3) -> 2 (Inbound 1)
    assert opts[0]["id"] == 2
    assert opts[0]["subSortIndex"] == -1
    assert opts[1]["id"] == 3
    assert opts[1]["subSortIndex"] == 1
    assert opts[2]["id"] == 1
    assert opts[2]["subSortIndex"] == 2

"""Тесты безопасности кластера: все мутации и очистки клиентов выполняются строго на Primary."""
from unittest.mock import AsyncMock, Mock, patch
import pytest

from services.xui import (
    delete_depleted_clients_everywhere,
    delete_orphan_clients_everywhere,
    delete_orphan_clients_on_nodes,
    disable_client,
    bulk_enable_clients,
    bulk_disable_clients,
)


@pytest.mark.asyncio
async def test_delete_depleted_runs_only_on_primary():
    mock_resp = Mock()
    mock_resp.json.return_value = {"success": True, "obj": 5}

    mock_client = SimpleNamespaceMock(
        _url=Mock(return_value="http://primary/panel/api/clients/delDepleted"),
        _post=AsyncMock(return_value=mock_resp),
        max_retries=1,
    )
    mock_api = Mock(client=mock_client)

    with patch("services.xui.get_api", AsyncMock(return_value=mock_api)), \
         patch("services.xui.get_api_for_node") as mock_node_api, \
         patch("services.xui._throttle", AsyncMock()):
        stats = await delete_depleted_clients_everywhere()

        assert stats["nodes"] == 1
        assert stats["deleted"] == 5
        assert stats["failed"] == 0
        mock_client._post.assert_awaited_once()
        mock_node_api.assert_not_called()


@pytest.mark.asyncio
async def test_delete_orphans_runs_only_on_primary():
    mock_resp = Mock()
    mock_resp.json.return_value = {"success": True, "obj": 2}

    mock_client = SimpleNamespaceMock(
        _url=Mock(return_value="http://primary/panel/api/clients/delOrphans"),
        _post=AsyncMock(return_value=mock_resp),
        max_retries=1,
    )
    mock_api = Mock(client=mock_client)

    with patch("services.xui.get_api", AsyncMock(return_value=mock_api)), \
         patch("services.xui.get_api_for_node") as mock_node_api, \
         patch("services.xui._throttle", AsyncMock()):
        stats = await delete_orphan_clients_everywhere()

        assert stats["nodes"] == 1
        assert stats["deleted"] == 2
        assert stats["failed"] == 0
        mock_client._post.assert_awaited_once()
        mock_node_api.assert_not_called()

        stats_nodes = await delete_orphan_clients_on_nodes([{"id": 2, "host": "secondary"}])
        assert stats_nodes["nodes"] == 1
        mock_node_api.assert_not_called()


@pytest.mark.asyncio
async def test_disable_client_runs_on_primary_without_touching_secondaries():
    mock_resp = Mock()
    mock_resp.json.return_value = {
        "success": True,
        "obj": {"changed": 1, "skipped": []},
    }

    mock_client = SimpleNamespaceMock(
        _url=Mock(return_value="http://primary/panel/api/clients/bulkDisable"),
        _post=AsyncMock(return_value=mock_resp),
        max_retries=1,
    )
    mock_api = Mock(client=mock_client)

    with patch("services.xui.get_api", AsyncMock(return_value=mock_api)), \
         patch("services.xui.get_api_for_node") as mock_node_api, \
         patch("services.xui._throttle", AsyncMock()):
        res = await disable_client("tg123456789")

        assert res is True
        mock_client._post.assert_awaited_once()
        mock_node_api.assert_not_called()


@pytest.mark.asyncio
async def test_bulk_enable_and_disable_endpoints():
    mock_resp = Mock()
    mock_resp.json.return_value = {
        "success": True,
        "obj": {"changed": 2, "skipped": []},
    }

    mock_client = SimpleNamespaceMock(
        _url=Mock(side_effect=lambda p: f"http://primary/{p}"),
        _post=AsyncMock(return_value=mock_resp),
        max_retries=1,
    )
    mock_api = Mock(client=mock_client)

    with patch("services.xui.get_api", AsyncMock(return_value=mock_api)), \
         patch("services.xui._throttle", AsyncMock()):
        res_enable = await bulk_enable_clients(["tg111", "tg222"], enable=True)
        assert res_enable["changed"] == 2

        res_disable = await bulk_disable_clients(["tg111", "tg222"])
        assert res_disable["changed"] == 2


class SimpleNamespaceMock:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

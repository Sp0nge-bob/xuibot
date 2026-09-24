"""Тесты создания бэкапа и выгрузки баз данных нод 3x-ui."""
from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.backup import create_backup_archive, send_backup_to_admins


import shutil

_TEST_TMP = Path(__file__).resolve().parent / "_tmp_backup"


@pytest.fixture
def mock_db_file(monkeypatch: pytest.MonkeyPatch):
    if _TEST_TMP.exists():
        shutil.rmtree(_TEST_TMP, ignore_errors=True)
    _TEST_TMP.mkdir(parents=True, exist_ok=True)

    db_file = _TEST_TMP / "bot.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test_table (val) VALUES ('test')")
    conn.commit()
    conn.close()

    monkeypatch.setattr("services.backup.DB_PATH", str(db_file))
    backup_dir = _TEST_TMP / "backups"
    monkeypatch.setattr("services.backup._BACKUP_DIR", backup_dir)

    yield db_file

    if _TEST_TMP.exists():
        shutil.rmtree(_TEST_TMP, ignore_errors=True)


@pytest.mark.asyncio
async def test_create_backup_archive_with_nodes(mock_db_file: Path, monkeypatch: pytest.MonkeyPatch):
    mock_nodes = [
        {"id": 1, "name": "Node-NL", "host": "https://nl.example.com", "enabled": 1},
        {"id": 2, "name": "Node DE", "host": "https://de.example.com", "enabled": 1},
    ]

    async def fake_list_nodes(enabled_only: bool = True):
        return mock_nodes

    monkeypatch.setattr("services.backup.list_nodes", fake_list_nodes)

    mock_api = MagicMock()
    mock_api.server = MagicMock()

    async def fake_get_db(save_path: str):
        with open(save_path, "wb") as f:
            f.write(b"SQLITE_XUI_DUMP")

    mock_api.server.get_db = AsyncMock(side_effect=fake_get_db)

    async def fake_get_api_for_node(node: dict):
        return mock_api

    monkeypatch.setattr("services.backup.get_api_for_node", fake_get_api_for_node)

    archive_path = await create_backup_archive()
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path, "r") as zf:
        namelist = zf.namelist()
        assert "bot.db" in namelist
        assert "manifest.json" in namelist
        assert "restore.txt" in namelist
        assert "nodes/node_1_Node-NL.db" in namelist
        assert "nodes/node_2_Node_DE.db" in namelist

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        nodes_backup = manifest.get("nodes_backup")
        assert nodes_backup is not None
        assert nodes_backup["total"] == 2
        assert nodes_backup["succeeded"] == 2
        assert nodes_backup["failed"] == 0


@pytest.mark.asyncio
async def test_create_backup_resilient_on_node_failure(mock_db_file: Path, monkeypatch: pytest.MonkeyPatch):
    mock_nodes = [
        {"id": 1, "name": "Healthy", "host": "https://nl.example.com", "enabled": 1},
        {"id": 2, "name": "Offline", "host": "https://offline.example.com", "enabled": 1},
    ]

    async def fake_list_nodes(enabled_only: bool = True):
        return mock_nodes

    monkeypatch.setattr("services.backup.list_nodes", fake_list_nodes)

    async def fake_get_api_for_node(node: dict):
        if node["id"] == 2:
            raise ConnectionError("Timeout connecting to node 2")
        mock_api = MagicMock()
        mock_api.server = MagicMock()

        async def fake_get_db(save_path: str):
            with open(save_path, "wb") as f:
                f.write(b"SQLITE_XUI_DUMP_OK")

        mock_api.server.get_db = AsyncMock(side_effect=fake_get_db)
        return mock_api

    monkeypatch.setattr("services.backup.get_api_for_node", fake_get_api_for_node)

    archive_path = await create_backup_archive()
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path, "r") as zf:
        namelist = zf.namelist()
        assert "bot.db" in namelist
        assert "manifest.json" in namelist
        assert "nodes/node_1_Healthy.db" in namelist
        assert "nodes/node_2_Offline.db" not in namelist

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        nodes_backup = manifest.get("nodes_backup")
        assert nodes_backup["total"] == 2
        assert nodes_backup["succeeded"] == 1
        assert nodes_backup["failed"] == 1


@pytest.mark.asyncio
async def test_send_backup_to_admins_caption(mock_db_file: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("services.backup.list_nodes", AsyncMock(return_value=[]))
    monkeypatch.setattr("services.backup.settings.BOT_ADMINS", [123456])

    fake_bot = MagicMock()
    fake_bot.send_document = AsyncMock()

    import sys
    fake_bot_module = MagicMock()
    fake_bot_module.bot = fake_bot
    monkeypatch.setitem(sys.modules, "bot", fake_bot_module)

    res = await send_backup_to_admins(source="manual")
    assert res["ok"] is True
    assert res["sent"] == 1
    assert fake_bot.send_document.called

    call_args = fake_bot.send_document.call_args
    assert call_args is not None
    caption = call_args.kwargs.get("caption", "")
    assert "Бэкап бота" in caption

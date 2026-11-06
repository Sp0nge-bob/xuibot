"""Тесты для кнопки повторной проверки доступности ноды и восстановления доступа."""
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import db.connection as db_conn
import db.database as db_mod
import db.xui_nodes as nodes_db
from config.settings import settings
from services.node_alerts import (
    node_down_alert_kb,
    node_up_alert_kb,
    process_health_transitions,
)


@pytest.fixture(autouse=True)
async def _setup_isolated_bot_db(monkeypatch):
    tmp_dir = Path(__file__).resolve().parent.parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    db_file = tmp_dir / f"node_alert_test_{uuid.uuid4().hex}.db"
    await db_conn.close_connection()
    monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "DB_PATH", str(db_file))
    monkeypatch.setattr(nodes_db, "_INIT_DONE", False)
    monkeypatch.setattr(nodes_db, "_INIT_IN_PROGRESS", False)
    import services.crypto as crypto_mod
    monkeypatch.setattr(crypto_mod, "_cached_fernet", None)
    monkeypatch.setattr(crypto_mod, "_cached_candidates", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "pentest_test_secret_key_32chars_long_123456")
    await db_mod.init_db()
    try:
        yield
    finally:
        await db_conn.close_connection()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


def test_node_alert_keyboards():
    down_kb = node_down_alert_kb(42)
    buttons = [btn for row in down_kb.inline_keyboard for btn in row]
    callbacks = [b.callback_data for b in buttons]
    texts = [b.text for b in buttons]

    assert "adm:node:retry_alert:42" in callbacks
    assert "adm:node:42" in callbacks
    assert any("Проверить и восстановить доступ" in t for t in texts)

    up_kb = node_up_alert_kb(42)
    up_callbacks = [b.callback_data for row in up_kb.inline_keyboard for b in row]
    assert "adm:node:42" in up_callbacks


@pytest.mark.asyncio
async def test_process_health_transitions_attaches_keyboard(monkeypatch):
    """Проверяет, что при переходе в down алерт админу отправляется с кнопкой восстановления."""
    sent_messages = []

    async def mock_send_message(chat_id, text, **kwargs):
        sent_messages.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})

    monkeypatch.setattr("bot.sender.send_message", mock_send_message)
    monkeypatch.setattr(settings, "BOT_ADMINS", [111222])

    node_id = await nodes_db.create_node(
        name="DE",
        host="https://germany.example.com",
        username="u",
        password="p",
        is_primary=False,
        is_enabled=True,
    )

    # Первый вызов — baseline (healthy)
    await process_health_transitions([{"node_id": node_id, "ok": True}])
    assert len(sent_messages) == 0

    # Второй вызов — переход в down
    await process_health_transitions([{
        "node_id": node_id,
        "ok": False,
        "error": "RuntimeError: inbounds/list и clients/list недоступны",
    }])

    assert len(sent_messages) == 1
    alert = sent_messages[0]
    assert "Нода недоступна" in alert["text"]
    assert "DE" in alert["text"]
    kb = alert["kwargs"].get("reply_markup")
    assert kb is not None
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert f"adm:node:retry_alert:{node_id}" in callbacks


@pytest.mark.asyncio
async def test_cb_node_retry_alert_success(monkeypatch):
    """Успешное восстановление доступности через кнопку."""
    import bot.admin_nodes as admin_nodes_mod
    from bot.admin_nodes import cb_node_retry_alert

    admin_id = 111222
    monkeypatch.setattr(admin_nodes_mod, "is_admin", lambda uid: uid == admin_id)

    node_id = await nodes_db.create_node(
        name="DE",
        host="https://germany.example.com",
        username="u",
        password="p",
        is_primary=False,
        is_enabled=True,
    )
    # Помечаем ноду как нездоровую
    await nodes_db.record_health_check(node_id, ok=False, latency_ms=100, error="Network error")

    # Патчим check_node_health в bot.admin_nodes
    async def mock_health(node, timeout_sec=None):
        await nodes_db.record_health_check(node_id, ok=True, latency_ms=45, error=None)
        return {
            "node_id": node_id,
            "name": "DE",
            "ok": True,
            "latency_ms": 45,
            "error": None,
        }

    monkeypatch.setattr(admin_nodes_mod, "check_node_health", mock_health)

    cb_msg = AsyncMock()
    cb = SimpleNamespace(
        from_user=SimpleNamespace(id=admin_id),
        data=f"adm:node:retry_alert:{node_id}",
        message=cb_msg,
        answer=AsyncMock(),
    )

    await cb_node_retry_alert(cb)

    assert cb_msg.edit_text.called or cb_msg.answer.called
    sent_text = (cb_msg.edit_text.call_args or cb_msg.answer.call_args)[0][0]
    assert "Нода успешно восстановлена" in sent_text
    assert "online" in sent_text
    assert "45 мс" in sent_text

    # Проверяем, что в БД нода теперь is_healthy = 1
    updated = await nodes_db.get_node(node_id)
    assert updated["is_healthy"] == 1


@pytest.mark.asyncio
async def test_cb_node_retry_alert_failure(monkeypatch):
    """Повторная проверка показала, что нода всё ещё недоступна."""
    import bot.admin_nodes as admin_nodes_mod
    from bot.admin_nodes import cb_node_retry_alert

    admin_id = 111222
    monkeypatch.setattr(admin_nodes_mod, "is_admin", lambda uid: uid == admin_id)

    node_id = await nodes_db.create_node(
        name="DE",
        host="https://germany.example.com",
        username="u",
        password="p",
        is_primary=False,
        is_enabled=True,
    )

    async def mock_health(node, timeout_sec=None):
        await nodes_db.record_health_check(node_id, ok=False, latency_ms=1500, error="Connection refused")
        return {
            "node_id": node_id,
            "name": "DE",
            "ok": False,
            "latency_ms": 1500,
            "error": "Connection refused",
        }

    monkeypatch.setattr(admin_nodes_mod, "check_node_health", mock_health)

    cb_msg = AsyncMock()
    cb = SimpleNamespace(
        from_user=SimpleNamespace(id=admin_id),
        data=f"adm:node:retry_alert:{node_id}",
        message=cb_msg,
        answer=AsyncMock(),
    )

    await cb_node_retry_alert(cb)

    assert cb_msg.edit_text.called or cb_msg.answer.called
    sent_text = (cb_msg.edit_text.call_args or cb_msg.answer.call_args)[0][0]
    assert "всё ещё недоступна" in sent_text
    assert "Connection refused" in sent_text

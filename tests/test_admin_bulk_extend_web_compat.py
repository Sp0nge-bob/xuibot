import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from config.settings import settings
import db.connection as db_conn
import db.database as db
from services.admin_bulk_extend import bulk_add_days_to_all_active
from services.expiry_reminders import send_expiry_reminders


@pytest.fixture(autouse=True)
async def _setup_isolated_db(monkeypatch):
    tmp_dir = Path(__file__).resolve().parent.parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    db_file = tmp_dir / f"test_web_compat_{uuid.uuid4().hex}.db"
    await db_conn.close_connection()
    monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
    monkeypatch.setattr(db, "DB_PATH", str(db_file))
    await db.init_db()
    try:
        yield
    finally:
        await db_conn.close_connection()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_bulk_extend_handles_web_subscription_null_tg_id():
    # Создаем подписку без tg_id (web user)
    async with db.get_db() as conn:
        await conn.execute(
            """INSERT INTO subscriptions (
                tg_id, sub_id, client_email, email_account, start_date, end_date, is_active, origin
            ) VALUES (
                NULL, 'sub_web_123', 'web_test_client', 'user@example.com', '2026-01-01', '2026-02-01', 1, 'web'
            )"""
        )
        await conn.commit()

    with patch("services.admin_bulk_extend.bulk_adjust_client_days", new_callable=AsyncMock) as mock_adjust, \
         patch("services.admin_bulk_extend.bulk_enable_clients", new_callable=AsyncMock) as mock_enable:
        mock_adjust.return_value = {"adjusted": 1, "skipped": []}
        res = await bulk_add_days_to_all_active(days=7, admin_tg_id=999)

    assert res["days"] == 7
    assert res["db_updated"] == 1
    assert res["db_failed"] == 0
    assert res["notify_ids"] == []


@pytest.mark.asyncio
async def test_expiry_reminders_handles_web_subscription_null_tg_id():
    # Создаем подписку без tg_id с истекающим сроком
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    soon = now + timedelta(days=2)
    async with db.get_db() as conn:
        await conn.execute(
            """INSERT INTO subscriptions (
                tg_id, sub_id, client_email, email_account, start_date, end_date, is_active, origin
            ) VALUES (
                NULL, 'sub_web_exp', 'web_exp_client', 'user@example.com', '2026-01-01', ?, 1, 'web'
            )""",
            (soon.isoformat(),),
        )
        await conn.commit()

    with patch("bot.sender.send_message", new_callable=AsyncMock) as mock_send:
        res = await send_expiry_reminders()

    assert res["failed"] == 0

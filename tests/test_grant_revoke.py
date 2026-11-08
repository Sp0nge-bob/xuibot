"""Тесты для отслеживания и отзыва grant-промокодов."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from config.settings import settings
import db.connection as db_conn
import db.database as db_mod
import db.xui_nodes as xui_nodes_mod
import db.promo_codes as promo_db
import db.database as db
from services.grant_revoke import revoke_grant_promo_use


@pytest.fixture(autouse=True)
async def _setup_isolated_db(monkeypatch):
    tmp_dir = Path(__file__).resolve().parent.parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    db_file = tmp_dir / f"test_grant_{uuid.uuid4().hex}.db"
    await db_conn.close_connection()
    monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "DB_PATH", str(db_file))
    monkeypatch.setattr(xui_nodes_mod, "_INIT_DONE", False)
    monkeypatch.setattr(xui_nodes_mod, "_INIT_IN_PROGRESS", False)
    import services.crypto as crypto_mod
    monkeypatch.setattr(crypto_mod, "_cached_fernet", None)
    monkeypatch.setattr(crypto_mod, "_cached_candidates", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "grant_test_secret_key_32chars_long_123456")
    await db.init_db()
    await promo_db.init_promo_tables()
    try:
        yield
    finally:
        await db_conn.close_connection()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_grant_promo_uses_listing_and_count():
    promo = await promo_db.create_promo_code(
        code="GRANT_FREE_1M",
        discount_type="grant",
        discount_value=0,
        plan_ids=["1m"],
        promo_type="grant",
        max_uses=10,
    )
    promo_id = promo["id"]

    await db.get_or_create_user(111, username="user_one", first_name="Alice")
    await db.get_or_create_user(222, username="user_two", first_name="Bob")

    sub1_id = await db.create_subscription(
        tg_id=111,
        order_id=None,
        inbound_id=1,
        client_email="tg111",
        client_uuid="uuid-1",
        sub_id="subid-111",
        days=30,
        traffic_gb=0,
    )

    await promo_db.record_grant_promo_use(
        promo_id=promo_id,
        tg_id=111,
        subscription_id=sub1_id,
    )

    await promo_db.record_grant_promo_use(
        promo_id=promo_id,
        tg_id=222,
    )

    count = await promo_db.count_promo_uses_detailed(promo_id)
    assert count == 2

    uses = await promo_db.list_promo_uses_detailed(promo_id, limit=10, offset=0)
    assert len(uses) == 2
    u1 = next(u for u in uses if u["tg_id"] == 111)
    assert u1["username"] == "user_one"
    assert u1["subscription_id"] == sub1_id
    assert u1["is_revoked"] == 0

    single_use = await promo_db.get_promo_use_by_id(u1["use_id"])
    assert single_use is not None
    assert single_use["code"] == "GRANT_FREE_1M"
    assert single_use["tg_id"] == 111


@pytest.mark.asyncio
async def test_revoke_grant_promo_use_deactivates_pure_grant():
    promo = await promo_db.create_promo_code(
        code="GRANT_REVOKE_ME",
        discount_type="grant",
        discount_value=0,
        plan_ids=["1m"],
        promo_type="grant",
        max_uses=5,
    )
    promo_id = promo["id"]

    await db.get_or_create_user(333, username="test_revoke", first_name="Charlie")
    sub_id = await db.create_subscription(
        tg_id=333,
        order_id=None,
        inbound_id=1,
        client_email="tg333",
        client_uuid="uuid-333",
        sub_id="subid-333",
        days=30,
        traffic_gb=0,
    )
    await db.add_grant_bonus_days(sub_id, 30)

    await promo_db.record_grant_promo_use(
        promo_id=promo_id,
        tg_id=333,
        subscription_id=sub_id,
    )
    uses = await promo_db.list_promo_uses_detailed(promo_id)
    use_id = uses[0]["use_id"]

    promo_before = await promo_db.get_promo_by_id(promo_id)
    assert promo_before["used_count"] == 1

    mock_bot = AsyncMock()
    with patch("services.grant_revoke.disable_client", new_callable=AsyncMock) as mock_disable:
        res = await revoke_grant_promo_use(
            use_id=use_id,
            admin_tg_id=999,
            bot_instance=mock_bot,
        )

    assert res["success"] is True
    assert res["action"] == "deactivated"
    assert res["still_active"] is False
    mock_disable.assert_awaited_once_with("tg333")

    # Проверка базы данных
    sub_after = await db.get_subscription_by_id(sub_id)
    assert sub_after["is_active"] == 0

    # Проверка promo_uses
    use_after = await promo_db.get_promo_use_by_id(use_id)
    assert use_after["is_revoked"] == 1
    assert use_after["revoked_at"] is not None

    # Проверка декремента счетчика
    promo_after = await promo_db.get_promo_by_id(promo_id)
    assert promo_after["used_count"] == 0

    # Проверка отправки уведомления пользователю
    mock_bot.send_message.assert_awaited_once()
    sent_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "отозван администратором" in sent_text
    assert "деактивирована" in sent_text


@pytest.mark.asyncio
async def test_revoke_grant_promo_use_shorten_active_sub():
    promo = await promo_db.create_promo_code(
        code="GRANT_SHORTEN",
        discount_type="grant",
        discount_value=0,
        plan_ids=["1m"],
        promo_type="grant",
    )
    promo_id = promo["id"]

    await db.get_or_create_user(444, username="test_paid_user")
    # Создаем подписку на 90 дней (например, 2 оплаченных месяца + 1 месяц по grant)
    order_id = await db.create_order(
        tg_id=444,
        plan_id="2m",
        plan_name="2 месяца",
        amount=500,
        payment_method="sbp",
        platega_tx_id="tx_order_paid_444",
    )
    await db.update_order_status("tx_order_paid_444", "paid")

    sub_id = await db.create_subscription(
        tg_id=444,
        order_id=order_id,
        inbound_id=1,
        client_email="tg444",
        client_uuid="uuid-444",
        sub_id="subid-444",
        days=90,
        traffic_gb=0,
    )
    await db.set_order_subscription_id(order_id, sub_id)
    await db.add_grant_bonus_days(sub_id, 30)

    await promo_db.record_grant_promo_use(
        promo_id=promo_id,
        tg_id=444,
        subscription_id=sub_id,
    )
    uses = await promo_db.list_promo_uses_detailed(promo_id)
    use_id = uses[0]["use_id"]

    mock_bot = AsyncMock()
    with patch("services.grant_revoke.extend_client", new_callable=AsyncMock) as mock_extend, \
         patch("services.grant_revoke.disable_client", new_callable=AsyncMock) as mock_disable:
        res = await revoke_grant_promo_use(
            use_id=use_id,
            admin_tg_id=999,
            bot_instance=mock_bot,
        )

    assert res["success"] is True
    assert res["action"] == "shortened"
    assert res["still_active"] is True
    mock_disable.assert_not_called()
    mock_extend.assert_awaited_once()

    sub_after = await db.get_subscription_by_id(sub_id)
    assert sub_after["is_active"] == 1
    assert sub_after["grant_bonus_days"] == 0

    mock_bot.send_message.assert_awaited_once()
    sent_text = mock_bot.send_message.call_args.kwargs["text"]
    assert "скорректирован" in sent_text


@pytest.mark.asyncio
async def test_revoke_grant_promo_use_twice_raises():
    promo = await promo_db.create_promo_code(
        code="GRANT_ONCE",
        discount_type="grant",
        discount_value=0,
        plan_ids=["1m"],
        promo_type="grant",
    )
    await promo_db.record_grant_promo_use(
        promo_id=promo["id"],
        tg_id=555,
    )
    uses = await promo_db.list_promo_uses_detailed(promo["id"])
    use_id = uses[0]["use_id"]

    await revoke_grant_promo_use(use_id=use_id)

    with pytest.raises(ValueError, match="уже была отозвана"):
        await revoke_grant_promo_use(use_id=use_id)


@pytest.mark.asyncio
async def test_revoke_invalid_use_id_raises():
    with pytest.raises(ValueError, match="не найдена"):
        await revoke_grant_promo_use(use_id=999999)


@pytest.mark.asyncio
async def test_revoke_grant_promo_web_user_null_tg_id():
    """Проверка отзыва промокода, активированного веб-пользователем (tg_id=None)."""
    promo = await promo_db.create_promo_code(
        code="GRANT_WEB_TEST",
        discount_type="grant",
        discount_value=0,
        plan_ids=["1m"],
        promo_type="grant",
    )
    # Записываем активацию без tg_id с email_account
    async with db.get_db() as conn:
        await conn.execute(
            """INSERT INTO promo_uses (promo_id, tg_id, email_account, used_at)
               VALUES (?, NULL, 'webuser@caelix.test', CURRENT_TIMESTAMP)""",
            (promo["id"],),
        )
        await conn.commit()
    uses = await promo_db.list_promo_uses_detailed(promo["id"])
    use_id = uses[0]["use_id"]

    res = await revoke_grant_promo_use(use_id=use_id, admin_tg_id=999)
    assert res["success"] is True
    assert res["tg_id"] is None

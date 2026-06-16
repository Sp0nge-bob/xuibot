"""
Полная симуляция PENDING через Platega API (симулятор) — все исходы.

Запуск: python scripts/test_pending_flow.py
Требует TEST_MODE=true в .env
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, ".")

from config.settings import settings
from db.database import init_db, create_order, get_order_by_platega_tx
from services import platega_simulator as sim
from services.platega_client import create_transaction
from services.platega import parse_create_response
from services.payment_flow import PendingTestOutcome, apply_pending_test_outcome, check_payment_status
from services.payment_processor import handle_platega_status

TEST_TG = 888777666
MOCK_FULFILL = ("OK: ключ выдан", None)


async def _create_pending_order() -> str:
    sim.clear_store()
    tx = await create_transaction(
        300,
        payment_method=settings.PLATEGA_SBP_METHOD,
        payload=f"tg:{TEST_TG}:1m:new",
        description="test pending",
    )
    parsed = parse_create_response(tx)
    tx_id = parsed["tx_id"]
    sim.set_scenario(tx_id, sim.SCENARIO_PENDING, check_status=sim.SCENARIO_PENDING)
    await create_order(
        tg_id=TEST_TG,
        plan_id="1m",
        plan_name="1 месяц",
        amount=300,
        platega_tx_id=tx_id,
        payment_method="sbp",
        order_type="new",
    )
    return tx_id


async def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  OK: {msg}")


async def test_check_still_pending(tx_id: str) -> None:
    print("\n1. PENDING → check (ещё не оплачено)")
    flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.CHECK_STILL_PENDING)
    await assert_true(flow.status == "PENDING", "status=PENDING")
    await assert_true(flow.result.handled, "handled")
    await assert_true(
        flow.result.user_message and "не поступила" in flow.result.user_message,
        "сообщение ожидания",
    )
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "pending", "заказ остаётся pending")


async def test_double_pending_check(tx_id: str) -> None:
    print("\n2. Двойная проверка PENDING")
    for i in range(2):
        flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.CHECK_STILL_PENDING)
        await assert_true(flow.status == "PENDING", f"проверка #{i+1} → PENDING")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "pending", "заказ всё ещё pending")


async def test_sim_confirm_check_pay(tx_id: str) -> str:
    print("\n3. PENDING → sim confirm (check_pay path)")
    with patch("services.payment_processor.fulfill_paid_order", new_callable=AsyncMock) as mock_ff:
        mock_ff.return_value = MOCK_FULFILL
        flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.SIM_CONFIRM)
    await assert_true(flow.status == "CONFIRMED", "status=CONFIRMED")
    await assert_true(flow.result.handled, "handled")
    await assert_true(mock_ff.called, "fulfillment вызван")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "paid", "заказ paid")
    return tx_id


async def test_already_paid(tx_id: str) -> None:
    print("\n4. Повторный CONFIRMED (already_paid)")
    flow = await check_payment_status(tx_id, source="test_repeat")
    await assert_true(flow.result.already_paid, "already_paid=True")


async def test_webhook_confirm() -> str:
    print("\n5. PENDING → webhook CONFIRMED")
    tx_id = await _create_pending_order()
    with patch("services.payment_processor.fulfill_paid_order", new_callable=AsyncMock) as mock_ff:
        mock_ff.return_value = MOCK_FULFILL
        flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.WEBHOOK_CONFIRM)
    await assert_true(flow.status == "CONFIRMED", "webhook CONFIRMED")
    await assert_true(mock_ff.called, "fulfillment через webhook")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "paid", "заказ paid")
    return tx_id


async def test_cancel() -> str:
    print("\n6. PENDING → CANCELED")
    tx_id = await _create_pending_order()
    flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.SIM_CANCEL)
    await assert_true(flow.status == "CANCELED", "status=CANCELED")
    await assert_true(
        flow.result.user_message and "отменён" in flow.result.user_message.lower(),
        "сообщение отмены",
    )
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "failed", "заказ failed")
    return tx_id


async def test_check_after_cancel(tx_id: str) -> None:
    print("\n7. Проверка после отмены")
    flow = await check_payment_status(tx_id, source="test_after_cancel")
    await assert_true(flow.status == "CANCELED", "status всё ещё CANCELED в API")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "failed", "заказ failed")


async def test_expired() -> str:
    print("\n8. PENDING → истекло 30 мин (expiresIn=null)")
    tx_id = await _create_pending_order()
    flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.SIM_EXPIRED)
    await assert_true(flow.status == "CANCELED", "expired → CANCELED")
    status_data = sim.simulate_get_status(tx_id)
    await assert_true(status_data.get("expiresIn") is None, "expiresIn сброшен")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "failed", "заказ failed")
    return tx_id


async def test_webhook_mismatch() -> None:
    print("\n9. Webhook CONFIRMED с неверной суммой")
    tx_id = await _create_pending_order()
    flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.WEBHOOK_MISMATCH)
    await assert_true(flow.result.amount_mismatch, "amount_mismatch")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "pending", "заказ остаётся pending при mismatch")


async def test_confirm_after_cancel_fails() -> None:
    print("\n10. Повторная оплата после отмены (sim confirm не срабатывает)")
    tx_id = await _create_pending_order()
    await apply_pending_test_outcome(tx_id, PendingTestOutcome.SIM_CANCEL)
    flow = await apply_pending_test_outcome(tx_id, PendingTestOutcome.SIM_CONFIRM)
    await assert_true(not flow.result.handled and not flow.status, "confirm после cancel отклонён")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "failed", "заказ остаётся failed")


async def test_webhook_cancel_on_paid_order() -> None:
    print("\n11. CANCELED webhook на уже оплаченном заказе")
    tx_id = await _create_pending_order()
    with patch("services.payment_processor.fulfill_paid_order", new_callable=AsyncMock) as mock_ff:
        mock_ff.return_value = MOCK_FULFILL
        await apply_pending_test_outcome(tx_id, PendingTestOutcome.WEBHOOK_CONFIRM)
    result = await handle_platega_status(
        tx_id, "CANCELED", source="test_late_cancel", notify=True,
    )
    await assert_true(result.handled, "handled")
    order = await get_order_by_platega_tx(tx_id)
    await assert_true(order["status"] == "failed", "paid → failed при chargeback/cancel callback")


async def main() -> None:
    if not settings.TEST_MODE:
        print("ERROR: установите TEST_MODE=true в .env")
        sys.exit(1)

    print("=== PENDING flow simulation (Platega API) ===")
    await init_db()

    tx = await _create_pending_order()
    await test_check_still_pending(tx)
    await test_double_pending_check(tx)

    tx_paid = await test_sim_confirm_check_pay(tx)
    await test_already_paid(tx_paid)

    await test_webhook_confirm()
    tx_cancel = await test_cancel()
    await test_check_after_cancel(tx_cancel)
    await test_expired()
    await test_webhook_mismatch()
    await test_confirm_after_cancel_fails()
    await test_webhook_cancel_on_paid_order()

    print("\n=== ALL PENDING TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
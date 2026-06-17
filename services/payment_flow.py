"""Проверка статуса Platega и обработка исходов (check_pay, webhook, тест-симуляция)."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from loguru import logger

from config.settings import settings
from services import platega_simulator as platega_sim
from services.payment_processor import PaymentProcessResult, handle_platega_status
from services.platega_client import get_transaction_status
from services.platega import parse_status_response


class PendingTestOutcome(str, Enum):
    CHECK_STILL_PENDING = "check_still_pending"
    SIM_CONFIRM = "sim_confirm"
    SIM_CANCEL = "sim_cancel"
    SIM_EXPIRED = "sim_expired"
    WEBHOOK_CONFIRM = "webhook_confirm"
    WEBHOOK_MISMATCH = "webhook_mismatch"


@dataclass
class PaymentFlowResult:
    result: PaymentProcessResult
    status: str
    callback_body: Optional[dict[str, Any]] = None


def _require_test_tx(tx_id: str) -> None:
    if not (settings.TEST_MODE and tx_id.startswith("test-")):
        raise ValueError("Тестовые исходы доступны только для test-* в TEST_MODE")


async def fetch_and_parse_status(tx_id: str) -> tuple[str, dict[str, Any]]:
    status_data = await get_transaction_status(tx_id)
    parsed = parse_status_response(status_data)
    return parsed["status"], status_data


def _build_callback_body(tx_id: str, status: str, *, amount_override: float | None = None) -> dict[str, Any]:
    body = platega_sim.build_callback_payload(tx_id, status)
    if amount_override is not None:
        body["amount"] = amount_override
    return body


async def process_payment_status(
    tx_id: str,
    status: str,
    *,
    source: str,
    callback_body: Optional[dict[str, Any]] = None,
    notify: bool = True,
) -> PaymentFlowResult:
    result = await handle_platega_status(
        tx_id,
        status,
        source=source,
        callback_body=callback_body,
        notify=notify,
    )
    return PaymentFlowResult(result=result, status=status, callback_body=callback_body)


async def check_payment_status(
    tx_id: str,
    *,
    simulate_confirm: bool = False,
    source: str = "check_pay",
    notify: bool = True,
) -> PaymentFlowResult:
    """Как кнопка «Проверить оплату»: GET status → handle_platega_status."""
    if simulate_confirm:
        _require_test_tx(tx_id)
        if not platega_sim.simulate_payment_completed(tx_id):
            return PaymentFlowResult(
                result=PaymentProcessResult(handled=False),
                status="",
            )

    status, status_data = await fetch_and_parse_status(tx_id)
    parsed = parse_status_response(status_data)
    if settings.TEST_MODE and tx_id.startswith("test-"):
        try:
            callback_body = _build_callback_body(tx_id, status)
        except KeyError:
            callback_body = {
                "id": tx_id,
                "status": status,
                "amount": parsed.get("amount"),
                "currency": parsed.get("currency") or "RUB",
            }
    else:
        callback_body = {
            "id": tx_id,
            "status": status,
            "amount": parsed.get("amount"),
            "currency": parsed.get("currency") or "RUB",
        }

    flow = await process_payment_status(
        tx_id, status, source=source, callback_body=callback_body, notify=notify,
    )
    return flow


async def apply_pending_test_outcome(
    tx_id: str,
    outcome: PendingTestOutcome,
    *,
    notify: bool = True,
) -> PaymentFlowResult:
    """Симуляция исходов PENDING для TEST_MODE (кнопки бота и автотесты)."""
    _require_test_tx(tx_id)

    if outcome == PendingTestOutcome.CHECK_STILL_PENDING:
        platega_sim.set_scenario(
            tx_id, platega_sim.SCENARIO_PENDING, check_status=platega_sim.SCENARIO_PENDING,
        )
        return await check_payment_status(tx_id, source="test_check_pay", notify=notify)

    if outcome == PendingTestOutcome.SIM_CONFIRM:
        return await check_payment_status(
            tx_id, simulate_confirm=True, source="test_sim_pay", notify=notify,
        )

    if outcome == PendingTestOutcome.SIM_CANCEL:
        platega_sim.simulate_cancel(tx_id)
        status, _ = await fetch_and_parse_status(tx_id)
        callback_body = _build_callback_body(tx_id, status)
        return await process_payment_status(
            tx_id, status, source="test_sim_cancel", callback_body=callback_body, notify=notify,
        )

    if outcome == PendingTestOutcome.SIM_EXPIRED:
        platega_sim.simulate_expired(tx_id)
        status, _ = await fetch_and_parse_status(tx_id)
        callback_body = _build_callback_body(tx_id, status)
        return await process_payment_status(
            tx_id, status, source="test_sim_expired", callback_body=callback_body, notify=notify,
        )

    if outcome == PendingTestOutcome.WEBHOOK_CONFIRM:
        if not platega_sim.simulate_payment_completed(tx_id):
            return PaymentFlowResult(result=PaymentProcessResult(handled=False), status="")
        status = platega_sim.SCENARIO_CONFIRMED
        callback_body = _build_callback_body(tx_id, status)
        return await process_payment_status(
            tx_id, status, source="test_webhook", callback_body=callback_body, notify=notify,
        )

    if outcome == PendingTestOutcome.WEBHOOK_MISMATCH:
        platega_sim.set_scenario(
            tx_id, platega_sim.SCENARIO_PENDING, check_status=platega_sim.SCENARIO_PENDING,
        )
        status = platega_sim.SCENARIO_CONFIRMED
        callback_body = _build_callback_body(tx_id, status, amount_override=0.01)
        return await process_payment_status(
            tx_id, status, source="test_webhook_mismatch", callback_body=callback_body, notify=notify,
        )

    raise ValueError(f"Unknown outcome: {outcome}")
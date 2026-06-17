"""Smoke test Platega simulator and payment processor helpers."""
import asyncio

from services.platega import build_create_request, format_request_preview, parse_create_response
from services.platega_simulator import (
    set_scenario,
    simulate_get_status,
    simulate_payment_completed,
    build_callback_payload,
    SCENARIO_PENDING,
    SCENARIO_CONFIRMED,
)
from services.platega_client import create_transaction
from config.settings import settings


async def main():
    assert settings.TEST_MODE, "TEST_MODE must be true for this script"
    req = build_create_request(299, payment_method=2, metadata={"userId": "1"})
    preview = format_request_preview(req["path"], req["body"])
    assert "POST" in preview and "299" in preview

    tx = await create_transaction(299, payment_method=2, payload="tg:1:plan:new")
    parsed = parse_create_response(tx)
    tid = parsed["tx_id"]
    assert tid.startswith("test-")

    set_scenario(tid, SCENARIO_PENDING, check_status=SCENARIO_PENDING)
    assert simulate_get_status(tid)["status"] == SCENARIO_PENDING
    simulate_payment_completed(tid)
    assert simulate_get_status(tid)["status"] == SCENARIO_CONFIRMED

    cb = build_callback_payload(tid, SCENARIO_CONFIRMED)
    assert cb["amount"] == 299.0
    assert cb["status"] == SCENARIO_CONFIRMED
    print("platega sim smoke: OK", tid)


if __name__ == "__main__":
    asyncio.run(main())
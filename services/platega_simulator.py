"""In-memory симулятор Platega API для TEST_MODE."""
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from loguru import logger

SCENARIO_CONFIRMED = "CONFIRMED"
SCENARIO_CANCELED = "CANCELED"
SCENARIO_PENDING = "PENDING"
SCENARIO_CHARGEBACKED = "CHARGEBACKED"
SCENARIO_CREATE_ERROR = "CREATE_ERROR"

ALL_SCENARIOS = (
    SCENARIO_CONFIRMED,
    SCENARIO_CANCELED,
    SCENARIO_PENDING,
    SCENARIO_CHARGEBACKED,
    SCENARIO_CREATE_ERROR,
)


@dataclass
class SimulatedTransaction:
    tx_id: str
    amount: float
    currency: str
    payment_method: int
    payload: str
    scenario: str = SCENARIO_PENDING
    check_status: str = SCENARIO_PENDING
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


_store: Dict[str, SimulatedTransaction] = {}


def clear_store() -> None:
    _store.clear()


def simulate_create(
    *,
    amount: int,
    currency: str,
    payment_method: int,
    description: str,
    payload: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tx_id = f"test-{uuid.uuid4()}"
    _store[tx_id] = SimulatedTransaction(
        tx_id=tx_id,
        amount=float(amount),
        currency=currency,
        payment_method=payment_method,
        payload=payload,
        description=description,
        metadata=metadata or {},
    )
    logger.info("Simulator: created tx {} amount={} {}", tx_id, amount, currency)
    return {
        "transactionId": tx_id,
        "status": "PENDING",
        "redirect": f"https://pay.platega.test/sim/{tx_id}",
        "expiresIn": "00:30:00",
        "paymentDetails": {"amount": amount, "currency": currency},
        "paymentMethod": str(payment_method),
    }


def set_scenario(tx_id: str, scenario: str, *, check_status: str | None = None) -> None:
    tx = _store.get(tx_id)
    if not tx:
        raise KeyError(f"Simulated tx {tx_id} not found")
    tx.scenario = scenario
    if check_status is not None:
        tx.check_status = check_status
    else:
        tx.check_status = scenario if scenario != SCENARIO_CREATE_ERROR else SCENARIO_PENDING


def get_transaction(tx_id: str) -> Optional[SimulatedTransaction]:
    return _store.get(tx_id)


def simulate_get_status(tx_id: str) -> Dict[str, Any]:
    tx = _store.get(tx_id)
    if not tx:
        raise KeyError(f"Simulated tx {tx_id} not found")
    status = tx.check_status
    expired = status != SCENARIO_PENDING
    return {
        "id": tx.tx_id,
        "status": status,
        "paymentDetails": {"amount": tx.amount, "currency": tx.currency},
        "paymentMethod": str(tx.payment_method),
        "expiresIn": None if expired else "00:30:00",
        "payload": tx.payload,
        "description": tx.description,
    }


def simulate_payment_completed(tx_id: str) -> bool:
    """Имитация оплаты: PENDING → CONFIRMED."""
    tx = _store.get(tx_id)
    if not tx or tx.check_status != SCENARIO_PENDING:
        return False
    tx.check_status = SCENARIO_CONFIRMED
    tx.scenario = SCENARIO_CONFIRMED
    return True


def simulate_cancel(tx_id: str) -> None:
    """Имитация отмены платежа клиентом или платёжной системой."""
    tx = _store.get(tx_id)
    if not tx:
        raise KeyError(f"Simulated tx {tx_id} not found")
    tx.scenario = SCENARIO_CANCELED
    tx.check_status = SCENARIO_CANCELED


def simulate_expired(tx_id: str) -> None:
    """Имитация истечения 30-минутного окна оплаты (статус CANCELED, без expiresIn)."""
    simulate_cancel(tx_id)


def build_callback_payload(tx_id: str, status: str | None = None) -> Dict[str, Any]:
    tx = _store.get(tx_id)
    if not tx:
        raise KeyError(f"Simulated tx {tx_id} not found")
    final_status = (status or tx.scenario).upper()
    return {
        "id": tx.tx_id,
        "amount": tx.amount,
        "currency": tx.currency,
        "status": final_status,
        "paymentMethod": tx.payment_method,
    }
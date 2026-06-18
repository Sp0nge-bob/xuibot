"""Фасад Platega: реальный API или симулятор в TEST_MODE."""
from typing import Any, Dict, Optional

from config.settings import settings

from . import platega as real
from . import platega_simulator as sim

PlategaAPIError = real.PlategaAPIError
build_create_request = real.build_create_request
format_request_preview = real.format_request_preview
parse_create_response = real.parse_create_response
parse_status_response = real.parse_status_response
format_create_error_message = real.format_create_error_message
get_return_urls = real.get_return_urls
verify_callback_headers = real.verify_callback_headers


async def create_transaction(
    amount: int,
    currency: str = "RUB",
    description: str = "Подписка",
    return_url: str = "https://t.me/",
    failed_url: str = "https://t.me/",
    payload: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    payment_method: Optional[int] = None,
) -> Dict[str, Any]:
    if settings.TEST_MODE:
        if payment_method is None:
            raise PlategaAPIError("В тестовом режиме нужен payment_method")
        return sim.simulate_create(
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            description=description,
            payload=payload,
            metadata=metadata,
        )
    return await real.create_transaction(
        amount=amount,
        currency=currency,
        description=description,
        return_url=return_url,
        failed_url=failed_url,
        payload=payload,
        metadata=metadata,
        payment_method=payment_method,
    )


async def get_transaction_status(transaction_id: str) -> Dict[str, Any]:
    if settings.TEST_MODE and transaction_id.startswith("test-"):
        return sim.simulate_get_status(transaction_id)
    return await real.get_transaction_status(transaction_id)
import json
from typing import Any, Dict, Optional, Tuple

import httpx
from loguru import logger

from config.settings import settings

BASE = settings.PLATEGA_BASE_URL.rstrip("/")

HEADERS = {
    "Content-Type": "application/json",
}


class PlategaAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, detail: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message


def get_return_urls(bot_username: str | None = None) -> Tuple[str, str]:
    if settings.PLATEGA_RETURN_URL:
        return_url = settings.PLATEGA_RETURN_URL
    elif bot_username:
        return_url = f"https://t.me/{bot_username.lstrip('@')}"
    else:
        return_url = "https://t.me/"

    failed_url = settings.PLATEGA_FAILED_URL or return_url
    return return_url, failed_url


def build_create_request(
    amount: int,
    *,
    currency: str = "RUB",
    description: str = "Подписка",
    return_url: str = "https://t.me/",
    failed_url: str = "https://t.me/",
    payload: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    payment_method: Optional[int] = None,
) -> Dict[str, Any]:
    path = "/transaction/process" if payment_method is not None else "/v2/transaction/process"
    body: Dict[str, Any] = {
        "paymentDetails": {
            "amount": amount,
            "currency": currency,
        },
        "description": description,
        "return": return_url,
        "failedUrl": failed_url,
        "payload": payload,
    }
    if payment_method is not None:
        body["paymentMethod"] = payment_method
    if metadata:
        body["metadata"] = metadata
    return {"path": path, "body": body}


def format_request_preview(path: str, body: Dict[str, Any]) -> str:
    url = f"{BASE}{path}"
    body_json = json.dumps(body, ensure_ascii=False, indent=2)
    return (
        f"<b>POST</b> <code>{url}</code>\n\n"
        f"<b>Заголовки:</b>\n"
        f"<code>X-MerchantId: ***\n"
        f"X-Secret: ***\n"
        f"Content-Type: application/json</code>\n\n"
        f"<b>Тело запроса:</b>\n"
        f"<pre>{body_json}</pre>"
    )


def normalize_platega_status(status: str) -> str:
    """Приводит статус к внутреннему виду (документация Platega: CHARGEBACK → CHARGEBACKED)."""
    s = (status or "").upper()
    if s == "CHARGEBACK":
        return "CHARGEBACKED"
    return s


def parse_create_response(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tx_id": data.get("transactionId") or data.get("id"),
        "redirect": data.get("redirect") or data.get("url"),
        "status": (data.get("status") or "PENDING").upper(),
        "expires_in": data.get("expiresIn"),
        "raw": data,
    }


def parse_status_response(data: Dict[str, Any]) -> Dict[str, Any]:
    status = normalize_platega_status(data.get("status") or "")
    details = data.get("paymentDetails") or {}
    return {
        "tx_id": data.get("id") or data.get("transactionId"),
        "status": status,
        "amount": details.get("amount"),
        "currency": details.get("currency"),
        "expires_in": data.get("expiresIn"),
        "raw": data,
    }


def format_create_error_message(exc: Exception) -> str:
    if isinstance(exc, PlategaAPIError):
        if exc.status_code == 401:
            return "❌ Ошибка авторизации Platega. Проверьте PLATEGA_MERCHANT_ID и PLATEGA_SECRET."
        if exc.status_code == 400:
            return f"❌ Неверные параметры платежа: {exc.detail}"
        return f"❌ Ошибка Platega ({exc.status_code or '?'}): {exc.detail}"
    return "❌ Не удалось создать платёж. Попробуйте позже."


async def _headers() -> Dict[str, str]:
    return {
        **HEADERS,
        "X-MerchantId": settings.PLATEGA_MERCHANT_ID,
        "X-Secret": settings.PLATEGA_SECRET,
    }


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
    req = build_create_request(
        amount,
        currency=currency,
        description=description,
        return_url=return_url,
        failed_url=failed_url,
        payload=payload,
        metadata=metadata,
        payment_method=payment_method,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{BASE}{req['path']}",
                json=req["body"],
                headers=await _headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200] if e.response else str(e)
            raise PlategaAPIError(
                f"Platega HTTP {e.response.status_code}",
                status_code=e.response.status_code,
                detail=detail,
            ) from e
        except httpx.HTTPError as e:
            raise PlategaAPIError(str(e)) from e

        data = resp.json()
        parsed = parse_create_response(data)
        logger.info("Platega transaction created: {} ({})", parsed["tx_id"], parsed["status"])
        return data


async def get_transaction_status(transaction_id: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.get(
                f"{BASE}/transaction/{transaction_id}",
                headers=await _headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:200] if e.response else str(e)
            raise PlategaAPIError(
                f"Platega HTTP {e.response.status_code}",
                status_code=e.response.status_code,
                detail=detail,
            ) from e
        except httpx.HTTPError as e:
            raise PlategaAPIError(str(e)) from e
        return resp.json()


async def verify_callback_headers(headers: Dict[str, str]) -> bool:
    mid = headers.get("x-merchantid") or headers.get("X-MerchantId")
    secret = headers.get("x-secret") or headers.get("X-Secret")
    return mid == settings.PLATEGA_MERCHANT_ID and secret == settings.PLATEGA_SECRET
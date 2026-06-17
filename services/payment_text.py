"""Тексты уведомлений об оплате."""
from datetime import datetime
from typing import Any, Dict, Optional


def _format_created_at(raw: Any) -> str:
    if not raw:
        return "—"
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", ""))
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except ValueError:
        return str(raw)[:19]


def payment_failed_user_text(
    order: Dict[str, Any],
    *,
    status: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """Сообщение пользователю о неуспешной/отклонённой оплате."""
    status_upper = (status or "FAILED").upper()
    status_titles = {
        "CANCELED": "❌ <b>Платёж отменён</b>",
        "FAILED": "❌ <b>Платёж не прошёл</b>",
        "CHARGEBACKED": "❌ <b>Платёж возвращён</b>",
    }
    header = title or status_titles.get(status_upper, "❌ <b>Платёж не прошёл</b>")

    order_type = order.get("order_type") or "new"
    action = "Продление" if order_type == "extend" else "Тариф"
    plan_name = order.get("plan_name") or "—"
    amount = int(order.get("amount") or 0)
    order_id = order.get("id") or "—"
    tx_id = order.get("platega_tx_id") or "—"
    created = _format_created_at(order.get("created_at"))

    lines = [
        header,
        "━━━━━━━━━━━━━━━━",
        "",
        f"📦 {action}: <b>{plan_name}</b>",
        f"💰 Сумма: <b>{amount} ₽</b>",
    ]
    if order.get("promo_code"):
        lines.append(f"🎟 Промокод: <code>{order['promo_code']}</code>")
    lines += [
        f"🆔 ID заказа: <code>{order_id}</code>",
        f"🆔 ID транзакции Platega: <code>{tx_id}</code>",
        f"🕐 Инициирован: <b>{created}</b>",
        "",
        "Создайте новый заказ в разделе «Тарифы», если хотите оплатить снова.",
    ]
    return "\n".join(lines)
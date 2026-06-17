"""Тексты уведомлений об оплате."""
from datetime import datetime
from typing import Any, Dict, Optional

from ui.theme import money, screen


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
        f"📦 {action}: <b>{plan_name}</b>",
        f"💰 Сумма: {money(amount)}",
    ]
    if order.get("promo_code"):
        lines.append(f"🎟 Промокод: <code>{order['promo_code']}</code>")
    lines += [
        f"🆔 ID заказа: <code>{order_id}</code>",
        f"🆔 ID транзакции Platega: <code>{tx_id}</code>",
        f"🕐 Инициирован: <b>{created}</b>",
    ]
    return screen(
        header,
        "\n".join(lines),
        hint="Создайте новый заказ в разделе «Тарифы», если хотите оплатить снова.",
    )


def _refund_access_line(reversal: Optional[Dict[str, Any]]) -> Optional[str]:
    if not reversal:
        return None
    action = reversal.get("action")
    if action == "revoked":
        return "🔒 <b>Доступ к VPN отключён</b> по этой оплате."
    if action == "shortened":
        end_date = reversal.get("end_date") or "—"
        return f"📅 <b>Срок подписки сокращён</b> — действует до <b>{end_date}</b>."
    if action == "disabled":
        return "🔒 <b>Доступ к VPN отключён</b> — оплаченный период аннулирован."
    return None


def refund_chargeback_user_text(
    order: Dict[str, Any],
    *,
    ticket_id: Optional[int] = None,
    reversal: Optional[Dict[str, Any]] = None,
) -> str:
    """Уведомление клиенту: Platega подтвердила возврат средств (CHARGEBACKED)."""
    plan_name = order.get("plan_name") or "—"
    amount = int(order.get("amount") or 0)
    order_id = order.get("id") or "—"
    tx_id = order.get("platega_tx_id") or "—"

    lines = [
        "Платёжная система подтвердила возврат:",
        "",
        f"📦 Тариф: <b>{plan_name}</b>",
        f"💰 Сумма: {money(amount)}",
        f"🧾 Заказ: <code>#{order_id}</code>",
        f"🆔 TX Platega: <code>{tx_id}</code>",
    ]
    if ticket_id:
        lines.append(f"🎫 Тикет: <code>#{ticket_id}</code>")
    access_line = _refund_access_line(reversal)
    if access_line:
        lines += ["", access_line]
    return screen(
        "✅ <b>Средства возвращены</b>",
        "\n".join(lines),
        hint="Средства поступят на счёт оплаты. Срок зачисления зависит от банка (обычно 1–14 дней).",
    )
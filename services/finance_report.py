"""Финансовый отчёт для админки (монетизация)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from db.connection import get_db

# Реальная оплата: paid, не симулятор, сумма > 0
_MONEY = """
    o.status = 'paid'
    AND COALESCE(o.platega_tx_id, '') NOT LIKE 'test-%'
    AND COALESCE(o.amount, 0) > 0
"""

_LINKED_TO_SUB = """
    (
      o.subscription_id = s.id
      OR (s.order_id IS NOT NULL AND o.id = s.order_id)
    )
"""


async def get_finance_report() -> dict[str, Any]:
    """Снимок метрик: платные (за деньги), grant, выручка."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day30 = (now - timedelta(days=30)).isoformat()
    month_iso = month_start.isoformat()

    async with get_db() as db:
        # Активные подписки с ≥1 денежным заказом
        async with db.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT s.tg_id)
            FROM subscriptions s
            WHERE s.is_active = 1
              AND s.client_email NOT LIKE 'tgfree%'
              AND EXISTS (
                SELECT 1 FROM orders o
                WHERE {_MONEY}
                  AND {_LINKED_TO_SUB}
              )
            """
        ) as cur:
            row = await cur.fetchone()
            money_subs = int(row[0] or 0)
            money_users = int(row[1] or 0)

        # Активные не-trial без денежных заказов (= grant / ручная / старые без order)
        async with db.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT s.tg_id)
            FROM subscriptions s
            WHERE s.is_active = 1
              AND s.client_email NOT LIKE 'tgfree%'
              AND NOT EXISTS (
                SELECT 1 FROM orders o
                WHERE {_MONEY}
                  AND {_LINKED_TO_SUB}
              )
            """
        ) as cur:
            row = await cur.fetchone()
            grant_subs = int(row[0] or 0)
            grant_users = int(row[1] or 0)

        # Из них явно с grant_bonus_days > 0
        async with db.execute(
            f"""
            SELECT COUNT(*)
            FROM subscriptions s
            WHERE s.is_active = 1
              AND s.client_email NOT LIKE 'tgfree%'
              AND COALESCE(s.grant_bonus_days, 0) > 0
              AND NOT EXISTS (
                SELECT 1 FROM orders o
                WHERE {_MONEY}
                  AND {_LINKED_TO_SUB}
              )
            """
        ) as cur:
            grant_marked = int((await cur.fetchone())[0] or 0)

        async with db.execute(
            """
            SELECT COUNT(*) FROM subscriptions
            WHERE is_active = 1 AND client_email LIKE 'tgfree%'
            """
        ) as cur:
            trial_subs = int((await cur.fetchone())[0] or 0)

        # Выручка
        async with db.execute(
            f"""
            SELECT
              COALESCE(SUM(o.amount), 0),
              COUNT(*),
              COALESCE(AVG(o.amount), 0),
              COALESCE(SUM(CASE WHEN o.order_type = 'extend' THEN o.amount ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN o.order_type = 'extend' THEN 1 ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN COALESCE(o.order_type, 'new') != 'extend' THEN o.amount ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN COALESCE(o.order_type, 'new') != 'extend' THEN 1 ELSE 0 END), 0),
              COALESCE(SUM(COALESCE(o.discount_amount, 0)), 0),
              MIN(COALESCE(o.paid_at, o.created_at))
            FROM orders o
            WHERE {_MONEY}
            """
        ) as cur:
            r = await cur.fetchone()
            total_revenue = int(r[0] or 0)
            orders_count = int(r[1] or 0)
            avg_check = float(r[2] or 0)
            extend_revenue = int(r[3] or 0)
            extend_orders = int(r[4] or 0)
            new_revenue = int(r[5] or 0)
            new_orders = int(r[6] or 0)
            discount_total = int(r[7] or 0)
            first_paid_at = r[8]

        async with db.execute(
            f"""
            SELECT COALESCE(SUM(o.amount), 0), COUNT(*)
            FROM orders o
            WHERE {_MONEY}
              AND COALESCE(o.paid_at, o.created_at) >= ?
            """,
            (month_iso,),
        ) as cur:
            r = await cur.fetchone()
            month_revenue = int(r[0] or 0)
            month_orders = int(r[1] or 0)

        async with db.execute(
            f"""
            SELECT COALESCE(SUM(o.amount), 0), COUNT(*)
            FROM orders o
            WHERE {_MONEY}
              AND COALESCE(o.paid_at, o.created_at) >= ?
            """,
            (day30,),
        ) as cur:
            r = await cur.fetchone()
            d30_revenue = int(r[0] or 0)
            d30_orders = int(r[1] or 0)

        # Скидки: промо vs реферал (по наличию promo_code)
        async with db.execute(
            f"""
            SELECT
              COALESCE(SUM(CASE WHEN COALESCE(o.promo_code, '') != '' THEN o.discount_amount ELSE 0 END), 0),
              COALESCE(SUM(CASE WHEN COALESCE(o.promo_code, '') = '' AND COALESCE(o.discount_amount, 0) > 0
                                THEN o.discount_amount ELSE 0 END), 0)
            FROM orders o
            WHERE {_MONEY}
            """
        ) as cur:
            r = await cur.fetchone()
            discount_promo = int(r[0] or 0)
            discount_referral = int(r[1] or 0)

    # Средняя выручка в месяц за всё время
    avg_month = 0.0
    months = 0.0
    if first_paid_at and total_revenue > 0:
        try:
            first = datetime.fromisoformat(str(first_paid_at).replace("Z", ""))
            days = max(1.0, (now - first).total_seconds() / 86400.0)
            months = max(1.0 / 30.0, days / 30.437)  # минимум доля месяца
            avg_month = total_revenue / months
        except ValueError:
            avg_month = float(d30_revenue)

    return {
        "money_subs": money_subs,
        "money_users": money_users,
        "grant_subs": grant_subs,
        "grant_users": grant_users,
        "grant_marked": grant_marked,
        "trial_subs": trial_subs,
        "total_revenue": total_revenue,
        "orders_count": orders_count,
        "avg_check": avg_check,
        "month_revenue": month_revenue,
        "month_orders": month_orders,
        "d30_revenue": d30_revenue,
        "d30_orders": d30_orders,
        "avg_month_revenue": avg_month,
        "months_span": months,
        "new_revenue": new_revenue,
        "new_orders": new_orders,
        "extend_revenue": extend_revenue,
        "extend_orders": extend_orders,
        "discount_total": discount_total,
        "discount_promo": discount_promo,
        "discount_referral": discount_referral,
        "first_paid_at": first_paid_at,
        "generated_at": now.isoformat(timespec="seconds") + "Z",
    }


def format_finance_report_text(data: dict[str, Any]) -> str:
    def money(n: int | float) -> str:
        return f"{int(round(n)):,}".replace(",", " ")

    first = data.get("first_paid_at") or "—"
    if first and first != "—":
        try:
            first = datetime.fromisoformat(str(first).replace("Z", "")).strftime("%d.%m.%Y")
        except ValueError:
            first = str(first)[:10]

    months = data.get("months_span") or 0
    months_label = f"{months:.1f}" if months else "—"

    return (
        "📈 <b>Финансовый отчёт</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "<b>Активные подписки</b>\n"
        f"💰 За деньги: <b>{data['money_subs']}</b> подп. "
        f"(<b>{data['money_users']}</b> чел.)\n"
        f"🎁 Grant / без оплаты: <b>{data['grant_subs']}</b> подп. "
        f"(<b>{data['grant_users']}</b> чел.)"
        f"{' · с меткой grant: <b>' + str(data['grant_marked']) + '</b>' if data.get('grant_marked') else ''}\n"
        f"🧪 Пробные: <b>{data['trial_subs']}</b>\n\n"
        "<b>Выручка</b> <i>(paid, не test-, amount &gt; 0)</i>\n"
        f"💵 Всего: <b>{money(data['total_revenue'])} ₽</b> "
        f"· заказов <b>{data['orders_count']}</b>\n"
        f"📅 Этот месяц: <b>{money(data['month_revenue'])} ₽</b> "
        f"({data['month_orders']} зак.)\n"
        f"📆 За 30 дней: <b>{money(data['d30_revenue'])} ₽</b> "
        f"({data['d30_orders']} зак.)\n"
        f"📊 В среднем в месяц: <b>{money(data['avg_month_revenue'])} ₽</b> "
        f"<i>(за {months_label} мес. с {first})</i>\n"
        f"🧾 Средний чек: <b>{money(data['avg_check'])} ₽</b>\n\n"
        "<b>Новые / продления</b>\n"
        f"🆕 Новые: <b>{money(data['new_revenue'])} ₽</b> ({data['new_orders']})\n"
        f"🔄 Продления: <b>{money(data['extend_revenue'])} ₽</b> ({data['extend_orders']})\n\n"
        "<b>Скидки (сумма −₽)</b>\n"
        f"Всего: <b>{money(data['discount_total'])} ₽</b>\n"
        f"🎟 Промо: <b>{money(data['discount_promo'])} ₽</b>\n"
        f"👥 Реферальные: <b>{money(data['discount_referral'])} ₽</b>\n\n"
        "<i>«За деньги» — есть ≥1 оплаченный заказ (не test-). "
        "Grant — активные без таких заказов.</i>"
    )

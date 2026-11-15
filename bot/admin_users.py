"""Хелперы списка подключённых пользователей в админке."""
from typing import Any

from config.trial import is_trial_email
from services.subscription_labels import subscription_short_label


def group_subscriptions_by_tg(users: list[dict[str, Any]]) -> dict[Any, list[dict]]:
    by_tg: dict[Any, list[dict]] = {}
    for u in users:
        tg_id = u.get("tg_id")
        key = tg_id if tg_id else f"web:{u.get('email_account') or u.get('client_email') or u.get('subscription_id') or u.get('id')}"
        by_tg.setdefault(key, []).append(u)
    return by_tg


def unique_tg_users_from_subs(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tg = group_subscriptions_by_tg(users)
    result: list[dict[str, Any]] = []
    for key, subs in by_tg.items():
        subs_sorted = sorted(subs, key=lambda s: s.get("end_date") or "", reverse=True)
        top = subs_sorted[0]
        tg_id = top.get("tg_id")
        result.append({
            "tg_id": tg_id,
            "subscription_id": top.get("subscription_id") or top.get("id"),
            "email_account": top.get("email_account"),
            "client_email": top.get("client_email"),
            "display_name": top.get("display_name"),
            "username": top.get("username"),
            "first_name": top.get("first_name"),
            "end_date": top.get("end_date"),
            "sub_count": len(subs),
        })
    result.sort(key=lambda u: u.get("end_date") or "", reverse=True)
    return result


def split_connected_users(users: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    paid: list[dict] = []
    trial: list[dict] = []
    for u in users:
        if is_trial_email(u.get("client_email")):
            trial.append(u)
        else:
            paid.append(u)
    return paid, trial


def tg_user_label(u: dict[str, Any]) -> str:
    tg_id = u.get("tg_id")
    if tg_id:
        if u.get("username"):
            return f"@{u['username']}"
        return u.get("first_name") or str(tg_id)
    return u.get("email_account") or u.get("client_email") or u.get("display_name") or "Web клиент"


def admin_users_menu_text(*, paid_count: int, trial_count: int) -> str:
    return (
        "👥 <b>Подключённые клиенты</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"✅ Платные: <b>{paid_count}</b> польз.\n"
        f"🎁 Пробные: <b>{trial_count}</b> польз.\n\n"
        "Выберите категорию или воспользуйтесь поиском."
    )


def admin_users_category_text(
    *,
    category: str,
    users: list[dict],
    limit: int,
) -> str:
    title = "✅ Платные клиенты" if category == "paid" else "🎁 Пробные клиенты"
    lines = [title, "━━━━━━━━━━━━━━━━", ""]
    if not users:
        lines.append("В этой категории активных клиентов нет.")
    else:
        lines.append(f"Показано: <b>{len(users)}</b> (до {limit} последних по сроку)")
    return "\n".join(lines)


def admin_user_subs_text(*, label: str, tg_id: int, subs: list[dict]) -> str:
    lines = [
        "👤 <b>Выбор подписки</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Клиент: {label}",
        f"TG ID: <code>{tg_id}</code>",
        "",
        f"Активных подписок: <b>{len(subs)}</b>",
        "",
        "Выберите подписку:",
    ]
    return "\n".join(lines)


def admin_users_search_text(query: str, users: list[dict]) -> str:
    lines = [
        f"🔍 <b>Найдено: {len(users)}</b>",
        f"Запрос: <code>{query}</code>",
        "",
    ]
    if not users:
        lines.append("Активных клиентов не найдено.")
    else:
        lines.append("Выберите клиента:")
    return "\n".join(lines)


def subscription_picker_button_label(sub: dict[str, Any]) -> str:
    end = (sub.get("end_date") or "")[:10]
    name = subscription_short_label(sub)
    email = sub.get("client_email") or ""
    if len(email) > 14:
        email = email[:11] + "..."
    return f"{name} · {email} · {end}"


def subscription_kind_label(client_email: str | None) -> str:
    return "🎁 Пробная" if is_trial_email(client_email) else "✅ Платная"